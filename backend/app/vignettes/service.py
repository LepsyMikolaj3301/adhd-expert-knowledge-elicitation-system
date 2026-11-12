import re
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_event
from app.core.db import utcnow
from app.core.errors import DomainError, invalid, not_found
from app.core.security import content_hash
from app.users.models import User
from app.vignettes.models import VersionStatus, Vignette, VignetteVersion
from app.vignettes.questions import QUESTION_IDS
from app.vignettes.schemas import VersionAdminView, VersionContent, VersionUpdate, VignetteAdminView

MIN_WORDS, MAX_WORDS = 120, 250

# Words that name what the vignette is about. Experts must read the text without them.
_CONSTRUCT_TERMS = re.compile(
    r"\b(?:adhd|attention[\s-]+deficit|methylphenidate|ritalin|concerta|medikinet|adderall"
    r"|vyvanse|elvanse|lisdexamfetamine|dexamfetamine|atomoxetine|strattera|guanfacine|intuniv)\b",
    re.IGNORECASE,
)
_ADD_UPPERCASE = re.compile(r"\bADD\b")  # uppercase only: the verb "add" is ordinary


def opening_words(text: str, count: int = 40) -> str:
    """The first words of a text, for a preview."""
    words = text.split()
    return " ".join(words[:count]) + ("…" if len(words) > count else "")


def validate_content(content: VersionContent) -> None:
    """Rules that span fields. Errors carry stable codes that the admin screens can name."""
    design = content.design
    # Every vignette asks Q4, so every vignette needs the what-if it is built on.
    if not (content.q4_whatif and content.q4_whatif.strip()):
        raise invalid("q4_without_whatif", "Q4 needs a what-if.")
    if design.is_control and design.planted_cues:
        raise invalid("control_with_cues", "A control vignette can't have planted cues.")
    if design.track == "text_analysis" and not design.knowledge_target:
        raise invalid("track_without_target", "The text_analysis track needs a knowledge target.")
    if content.variant and content.variant.arm == "B" and not content.variant.change:
        raise invalid("variant_b_without_change", "Arm B must say what it changes.")
    quotes = [cue.quote for cue in design.planted_cues]
    quotes += [confounder.quote for confounder in design.confounders]
    for quote in quotes:
        if quote not in content.text:
            raise invalid("span_not_in_text", "A design quote isn't in the text.", {"quote": quote})


def _new_version(vignette_id: UUID, number: int, content: VersionContent) -> VignetteVersion:
    return VignetteVersion(
        vignette_id=vignette_id,
        version=number,
        text=content.text,
        content_hash=content_hash(content.text),
        framing=content.framing,
        question_ids=list(QUESTION_IDS),
        q4_whatif=content.q4_whatif,
        patient_summary=content.patient_summary,
        variant=content.variant.model_dump(mode="json") if content.variant else None,
        design=content.design.model_dump(mode="json"),
    )


def check_construct_words(text: str, whatif: str | None, summary: str = "") -> None:
    """Publishing only: a draft may still be unfinished. Reports the first term found."""
    for field, value in (("text", text), ("q4_whatif", whatif or ""), ("patient_summary", summary)):
        found = _CONSTRUCT_TERMS.search(value) or _ADD_UPPERCASE.search(value)
        if found:
            term = found.group(0)
            raise invalid(
                "construct_word_in_text",
                f'The {field} contains "{term}", which names what the vignette is about. '
                "Reword it.",
                {"field": field, "term": term},
            )


async def create_vignette(
    db: AsyncSession, code: str, content: VersionContent, admin: User
) -> tuple[Vignette, VignetteVersion]:
    validate_content(content)
    vignette = Vignette(code=code, created_by=admin.id)
    db.add(vignette)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise DomainError("vignette_code_taken", f"{code} already exists.") from exc
    version = _new_version(vignette.id, 1, content)
    db.add(version)
    await db.flush()
    record_event(
        db,
        actor_id=admin.id,
        entity_type="vignette",
        entity_id=vignette.id,
        action="vignette_created",
        meta={"code": code},
    )
    return vignette, version


async def add_version(
    db: AsyncSession, vignette_id: UUID, content: VersionContent, admin: User
) -> VignetteVersion:
    validate_content(content)
    # Locked so that two simultaneous calls can't pick the same number.
    vignette = await db.scalar(select(Vignette).where(Vignette.id == vignette_id).with_for_update())
    if vignette is None:
        raise not_found("Vignette")
    latest = await db.scalar(
        select(func.max(VignetteVersion.version)).where(VignetteVersion.vignette_id == vignette_id)
    )
    version = _new_version(vignette_id, (latest or 0) + 1, content)
    db.add(version)
    await db.flush()
    record_event(
        db,
        actor_id=admin.id,
        entity_type="vignette_version",
        entity_id=version.id,
        action="version_created",
        meta={"version": version.version},
    )
    return version


async def version_and_code(db: AsyncSession, version_id: UUID) -> tuple[VignetteVersion, str]:
    row = (
        await db.execute(
            select(VignetteVersion, Vignette.code)
            .join(Vignette, Vignette.id == VignetteVersion.vignette_id)
            .where(VignetteVersion.id == version_id)
        )
    ).one()
    return row[0], row[1]


async def _lock_version(db: AsyncSession, version_id: UUID) -> VignetteVersion:
    version = await db.scalar(
        select(VignetteVersion).where(VignetteVersion.id == version_id).with_for_update()
    )
    if version is None:
        raise not_found("Vignette version")
    return version


async def update_version(
    db: AsyncSession, version_id: UUID, changes: VersionUpdate
) -> VignetteVersion:
    version = await _lock_version(db, version_id)
    if version.status != VersionStatus.DRAFT:
        raise DomainError("version_not_draft", "Only a draft version can be edited.")
    current = {
        "text": version.text,
        "framing": version.framing,
        "q4_whatif": version.q4_whatif,
        "patient_summary": version.patient_summary,
        "variant": version.variant,
        "design": version.design,
    }
    try:
        merged = VersionContent.model_validate(
            {**current, **changes.model_dump(exclude_unset=True)}
        )
    except ValidationError as exc:
        # E.g. an explicit null for a required field: valid for PATCH, not for the merged version.
        fields = [str(error["loc"][0]) for error in exc.errors() if error["loc"]]
        raise invalid("validation_error", "The change isn't valid.", {"fields": fields}) from exc
    validate_content(merged)
    version.text = merged.text
    version.content_hash = content_hash(merged.text)
    version.framing = merged.framing
    version.q4_whatif = merged.q4_whatif
    version.patient_summary = merged.patient_summary
    version.variant = merged.variant.model_dump(mode="json") if merged.variant else None
    version.design = merged.design.model_dump(mode="json")
    return version


async def publish_version(db: AsyncSession, version_id: UUID, admin: User) -> VignetteVersion:
    version = await _lock_version(db, version_id)
    if version.status != VersionStatus.DRAFT:
        raise DomainError("version_not_draft", "Only a draft version can be published.")
    words = len(version.text.split())
    if not MIN_WORDS <= words <= MAX_WORDS:
        raise invalid(
            "word_count_out_of_range",
            f"The text must be {MIN_WORDS}-{MAX_WORDS} words; it has {words}.",
            {"words": words},
        )
    if not version.patient_summary.strip():
        raise invalid("summary_missing", "Add a short description of the patient.")
    check_construct_words(version.text, version.q4_whatif, version.patient_summary)
    version.status = VersionStatus.PUBLISHED
    version.published_at = utcnow()
    record_event(
        db,
        actor_id=admin.id,
        entity_type="vignette_version",
        entity_id=version.id,
        action="version_published",
        from_state=VersionStatus.DRAFT,
        to_state=VersionStatus.PUBLISHED,
    )
    return version


async def retire_version(db: AsyncSession, version_id: UUID, admin: User) -> VignetteVersion:
    """Stops new assignments. Assignments already made run to the end on this version."""
    version = await _lock_version(db, version_id)
    if version.status != VersionStatus.PUBLISHED:
        raise DomainError("version_not_published", "Only a published version can be retired.")
    version.status = VersionStatus.RETIRED
    record_event(
        db,
        actor_id=admin.id,
        entity_type="vignette_version",
        entity_id=version.id,
        action="version_retired",
        from_state=VersionStatus.PUBLISHED,
        to_state=VersionStatus.RETIRED,
    )
    return version


async def list_vignettes(db: AsyncSession) -> list[VignetteAdminView]:
    versions = await db.scalars(
        select(VignetteVersion).order_by(VignetteVersion.vignette_id, VignetteVersion.version)
    )
    by_vignette: dict[UUID, list[VersionAdminView]] = {}
    for version in versions:
        by_vignette.setdefault(version.vignette_id, []).append(
            VersionAdminView.model_validate(version)
        )
    vignettes = await db.scalars(select(Vignette).order_by(Vignette.code))
    return [
        VignetteAdminView(
            id=vignette.id,
            code=vignette.code,
            created_at=vignette.created_at,
            versions=by_vignette.get(vignette.id, []),
        )
        for vignette in vignettes
    ]
