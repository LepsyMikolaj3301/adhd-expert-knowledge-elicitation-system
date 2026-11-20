"""Ranked units + the findings records -> LangChain Documents, one packed note each."""

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from langchain_core.documents import Document

from expert_knowledge_core.agreement import render_agreement
from expert_knowledge_core.notes import merge_groups, pack_block, pack_group_block
from expert_knowledge_core.records import is_readable
from expert_knowledge_rag.ranking import Grouping, UnitHit

logger = logging.getLogger(__name__)

SOURCE = "expert"


def local_id(hit: UnitHit) -> str:
    """`<session>-<vignette>-h3` is `h3` inside the record: the id ingestion prefixed."""
    prefix = f"{hit.session_id}-{hit.vignette_id}-"
    if not hit.id.startswith(prefix):
        raise ValueError(f"unit id {hit.id!r} does not start with {prefix!r}")
    return hit.id[len(prefix) :]


def _metadata(
    hits: Sequence[UnitHit], record: Mapping[str, Any] | None, merged: bool
) -> dict[str, Any]:
    first = hits[0]
    words = []
    if record is not None:
        by_id = {h["id"]: h for h in record["highlights"]}
        by_unit = {u["id"]: u for u in record["units"]}
        for hit in hits:
            unit = by_unit.get(local_id(hit))
            highlight = by_id.get((unit or {}).get("highlight") or "")
            if highlight:
                words.append({"text": highlight["text"], "direction": highlight["direction"]})
    return {
        "source": SOURCE,
        "unit_ids": [h.id for h in hits],
        "session_id": first.session_id,
        "expert_id": first.expert_id,
        "vignette_id": first.vignette_id,
        "vignette_version": first.vignette_version,
        "kinds": [h.kind for h in hits],
        "directions": [h.direction for h in hits],
        "patient_words": words,
        "score": first.score,  # the best unit of the note
        "merged": merged,
    }


def _local_ids(record: Any, hits: Sequence[UnitHit]) -> dict[str, str] | None:
    """Each hit's id inside the record, or None when the record can't be used to pack them: it is
    not a findings record this version reads, or a unit is not in it."""
    if not is_readable(record):
        return None
    in_record = {u["id"] for u in record["units"]}
    try:
        ids = {hit.id: local_id(hit) for hit in hits}
    except ValueError:
        return None
    return ids if all(local in in_record for local in ids.values()) else None


def _group_note(
    group_id: int, best: Sequence[UnitHit], grouping: Grouping, records: Mapping[str, Any]
) -> Document | None:
    """One note for every clinician who marked a passage, in the rank of the best hit. The
    agreement line counts all of them; the words quoted are those of at most GROUP_VOICES, the
    hits first. None when the best hit's record can't be read (the caller falls back)."""
    agreement = grouping.agreements[group_id]
    seen = {h.id for h in best}
    members = [*best, *(m for m in grouping.members.get(group_id, ()) if m.id not in seen)]
    by_session: dict[str, list[UnitHit]] = {}
    for member in members:
        by_session.setdefault(member.session_id, []).append(member)
    voices: list[tuple[Any, list[str]]] = []
    used: list[UnitHit] = []
    for session_id, session_hits in by_session.items():
        record = records.get(session_id)
        ids = _local_ids(record, session_hits)
        if record is None or ids is None:
            if session_id == best[0].session_id:
                return None
            continue
        voices.append((record, [ids[h.id] for h in session_hits]))
        used += session_hits
    words: list[dict[str, Any]] = []
    for record, unit_ids in voices:
        by_unit = {u["id"]: u for u in record["units"]}
        by_highlight = {h["id"]: h for h in record["highlights"]}
        for unit_id in unit_ids:
            h = by_highlight.get(by_unit[unit_id]["highlight"] or "")
            if h:
                words.append({"text": h["text"], "direction": h["direction"]})
    first = best[0]
    line = render_agreement(agreement)
    return Document(
        id=first.id,
        page_content=pack_group_block(voices, line),
        metadata={
            "source": SOURCE,
            "unit_ids": [h.id for h in used],
            "session_id": first.session_id,
            "expert_id": first.expert_id,
            "expert_ids": sorted({h.expert_id for h in used}),
            "vignette_id": first.vignette_id,
            "vignette_version": first.vignette_version,
            "kinds": [h.kind for h in used],
            "directions": [h.direction for h in used],
            "patient_words": words,
            "score": first.score,
            "merged": len(used) > 1,
            "group_id": group_id,
            "agreement": {
                "k": agreement.k,
                "n": agreement.n,
                "counts": dict(agreement.counts),
                "label": agreement.label,
                "line": line,
            },
        },
    )


def build_documents(
    hits: Sequence[UnitHit],
    records: Mapping[str, Any],
    *,
    merge: bool = True,
    grouping: Grouping | None = None,
) -> list[Document]:
    """One Document per note, in the rank of its best unit.

    With a `grouping`, the fragment units of clinicians who marked the same passage become one
    note with an agreement line and a few of their words (`_group_note`); case units and units
    in no group are packed as below.

    Units of one session that share a sentence become one note (each sentence once), as the
    evaluations packed them. A session whose `document` is not a findings record this version can
    read (for example the raw ChipDocument that `chips_eval` stores) gives one note per unit: the
    text that was embedded, with a warning.
    """
    notes: list[tuple[int, Document]] = []
    position = {hit.id: n for n, hit in enumerate(hits)}
    if grouping is not None:
        ungrouped: list[UnitHit] = []
        grouped: dict[int, list[UnitHit]] = {}
        for hit in hits:
            group_id = grouping.of_highlight.get(hit.highlight_id or "")
            if group_id is None or hit.kind != "fragment":
                ungrouped.append(hit)
            else:
                grouped.setdefault(group_id, []).append(hit)
        for group_id, best in grouped.items():
            note = _group_note(group_id, best, grouping, records)
            if note is None:
                ungrouped += best
            else:
                notes.append((position[best[0].id], note))
        hits = ungrouped

    by_session: dict[str, list[UnitHit]] = {}
    for hit in hits:
        by_session.setdefault(hit.session_id, []).append(hit)
    for session_id, session_hits in by_session.items():
        record = records.get(session_id)
        ids = _local_ids(record, session_hits)
        if record is None or ids is None:
            logger.warning(
                "session %s has no readable findings record: its units are returned as embedded",
                session_id,
            )
            for hit in session_hits:
                doc = Document(
                    id=hit.id, page_content=hit.embed_text, metadata=_metadata([hit], None, False)
                )
                notes.append((position[hit.id], doc))
            continue
        by_unit = {u["id"]: u for u in record["units"]}
        by_hit = {ids[h.id]: h for h in session_hits}
        groups = (
            merge_groups(by_unit, [ids[h.id] for h in session_hits])
            if merge
            else [[ids[h.id]] for h in session_hits]
        )
        for group in groups:
            members = sorted((by_hit[local] for local in group), key=lambda h: position[h.id])
            best = members[0]
            doc = Document(
                id=best.id,
                page_content=pack_block(record, group),
                metadata=_metadata(members, record, len(members) > 1),
            )
            notes.append((position[best.id], doc))
    return [doc for _, doc in sorted(notes, key=lambda n: n[0])]
