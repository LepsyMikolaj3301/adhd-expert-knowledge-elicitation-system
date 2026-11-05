"""Load vignette files (the fixture format) as drafts: `python -m app.cli import-vignettes`.

Each file keeps its text, framing, variant and design. The question set is the server's own, the
what-if comes from a separate file, and everything is checked before anything is written.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DomainError, invalid
from app.users.models import User
from app.vignettes import service
from app.vignettes.models import Vignette
from app.vignettes.schemas import VersionContent, VignetteCreate

_KEPT_FIELDS = ("text", "framing", "variant", "design")


@dataclass
class ImportResult:
    created: list[str]
    skipped: list[str]


def read_whatifs(path: Path) -> dict[str, str]:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise invalid("whatifs_unreadable", f"Can't read {path}: {exc}") from exc
    if not isinstance(data, dict) or not all(
        isinstance(code, str) and isinstance(whatif, str) for code, whatif in data.items()
    ):
        raise invalid("whatifs_unreadable", f"{path} must map vignette codes to what-if text.")
    return data


def _load(path: Path, whatifs: dict[str, str]) -> tuple[str, VersionContent]:
    raw = json.loads(path.read_text())
    code = raw.get("id")
    whatif = (whatifs.get(code) or "").strip() if isinstance(code, str) else ""
    if not whatif:
        raise invalid("whatif_missing", "no what-if for this vignette.")
    body = {key: raw[key] for key in _KEPT_FIELDS if raw.get(key) is not None}
    created = VignetteCreate.model_validate({**body, "code": code, "q4_whatif": whatif})
    content = VersionContent(**created.model_dump(exclude={"code"}))
    service.validate_content(content)
    return created.code, content


def plan_import(directory: Path, whatifs: dict[str, str]) -> dict[str, VersionContent]:
    """Reads and checks every file. Raises one error naming all the problems found."""
    files = sorted(directory.glob("V*.json")) if directory.is_dir() else []
    if not files:
        raise invalid("no_vignette_files", f"No V*.json files in {directory}.")

    contents: dict[str, VersionContent] = {}
    problems: list[str] = []
    for path in files:
        try:
            code, content = _load(path, whatifs)
            contents[code] = content
        except DomainError as exc:
            detail = f" {exc.details}" if exc.details else ""
            problems.append(f"{path.name}: {exc.message}{detail}")
        except (ValidationError, ValueError) as exc:
            problems.append(f"{path.name}: {exc}")
    problems += [
        f"{code}: a what-if but no vignette file."
        for code in sorted(set(whatifs) - {path.stem for path in files} - set(contents))
    ]
    if problems:
        raise invalid("import_refused", "Nothing was imported:\n  " + "\n  ".join(problems))
    return contents


async def import_vignettes(
    db: AsyncSession, directory: Path, whatifs: dict[str, str], admin: User
) -> ImportResult:
    """Creates a draft for every file whose code is new. Raises before writing if any is invalid."""
    contents = plan_import(directory, whatifs)
    existing = set(await db.scalars(select(Vignette.code).where(Vignette.code.in_(contents))))
    result = ImportResult(created=[], skipped=[])
    for code, content in contents.items():
        if code in existing:
            result.skipped.append(code)
            continue
        await service.create_vignette(db, code, content, admin)
        result.created.append(code)
    return result
