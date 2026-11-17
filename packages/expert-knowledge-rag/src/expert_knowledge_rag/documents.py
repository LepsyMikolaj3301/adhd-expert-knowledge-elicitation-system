"""Ranked units + the findings records -> LangChain Documents, one packed note each."""

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from langchain_core.documents import Document

from expert_knowledge_core.notes import merge_groups, pack_block
from expert_knowledge_core.records import is_readable
from expert_knowledge_rag.ranking import UnitHit

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


def build_documents(
    hits: Sequence[UnitHit], records: Mapping[str, Any], *, merge: bool = True
) -> list[Document]:
    """One Document per note, in the rank of its best unit.

    Units of one session that share a sentence become one note (each sentence once), as the
    evaluations packed them. A session whose `document` is not a findings record this version can
    read (for example the raw ChipDocument that `chips_eval` stores) gives one note per unit: the
    text that was embedded, with a warning.
    """
    by_session: dict[str, list[UnitHit]] = {}
    for hit in hits:
        by_session.setdefault(hit.session_id, []).append(hit)

    notes: list[tuple[int, Document]] = []
    position = {hit.id: n for n, hit in enumerate(hits)}
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
