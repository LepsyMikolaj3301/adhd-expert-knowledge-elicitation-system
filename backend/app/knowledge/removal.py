"""Taking ingested units out of the knowledge base: one unit, or everything an expert gave.

Retrieval reads the `chips` tables, so removing a unit deletes its rows there, in the same
transaction that marks it `removed`. The dense vectors of the other units don't depend on it, but
the BM25 weights are corpus-wide, so a `refit` job is queued for the worker
(app.jobs.handlers.refit).
"""

import json
from collections import defaultdict
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignments.models import Assignment
from app.audit.service import record_event
from app.jobs.models import Job, JobKind, JobStatus
from app.knowledge.findings import CASE
from app.knowledge.ingest import BM25_LOCK
from app.knowledge.models import KnowledgeUnit, UnitStatus
from app.vignettes.service import version_and_code


async def enqueue_refit(db: AsyncSession) -> None:
    """Queues a refit unless one is already waiting. One that is running doesn't count: it may
    have read the corpus before this transaction commits."""
    waiting = await db.scalar(
        select(Job.id).where(Job.kind == JobKind.REFIT, Job.status == JobStatus.QUEUED).limit(1)
    )
    if waiting is None:
        db.add(Job(kind=JobKind.REFIT, assignment_id=None))


async def remove_units(db: AsyncSession, units: list[KnowledgeUnit], actor_id: UUID) -> int:
    """Removes ingested `units` from retrieval and marks them removed. Returns how many."""
    units = [u for u in units if u.status == UnitStatus.INGESTED]
    if not units:
        return 0
    # The same lock as ingestion: its write and refit never see half of a removal.
    await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": BM25_LOCK})

    by_session: dict[str, list[KnowledgeUnit]] = defaultdict(list)
    for unit in units:
        by_session[str(unit.assignment_id)].append(unit)

    experts: set[str] = set()
    cases: set[tuple[str, int]] = set()
    for session_id, removed in by_session.items():
        assignment = await db.get(Assignment, removed[0].assignment_id)
        assert assignment is not None
        version, code = await version_and_code(db, assignment.vignette_version_id)
        experts.add(str(assignment.expert_id))
        cases.add((code, version.version))
        local_ids = {u.highlight_id or CASE for u in removed}
        await db.execute(
            text("DELETE FROM chips.finding_units WHERE id = ANY(:ids)"),
            {"ids": [f"{session_id}-{code}-{local}" for local in local_ids]},
        )
        left = await db.scalar(
            text("SELECT count(*) FROM chips.finding_units WHERE session_id = :sid"),
            {"sid": session_id},
        )
        if not left:
            await db.execute(
                text("DELETE FROM chips.elicitation_sessions WHERE id = :sid"), {"sid": session_id}
            )
        else:
            document = await db.scalar(
                text("SELECT document FROM chips.elicitation_sessions WHERE id = :sid"),
                {"sid": session_id},
            )
            if document is not None:
                document["units"] = [u for u in document["units"] if u["id"] not in local_ids]
                await db.execute(
                    text(
                        "UPDATE chips.elicitation_sessions SET document = CAST(:doc AS jsonb) "
                        "WHERE id = :sid"
                    ),
                    {"doc": json.dumps(document), "sid": session_id},
                )

    # What nothing points at any more, among what this touched only (other tiers live here too):
    # the patient's words no highlight cites, and experts with no session left.
    for code, version_number in cases:
        await db.execute(
            text(
                "DELETE FROM chips.cue_keys c WHERE c.vignette_id = :vid "
                "AND c.vignette_version = :ver "
                "AND NOT EXISTS (SELECT 1 FROM chips.highlights h WHERE h.cue_key_id = c.id) "
                "AND NOT EXISTS (SELECT 1 FROM chips.unit_cues u WHERE u.cue_key_id = c.id)"
            ),
            {"vid": code, "ver": version_number},
        )
    await db.execute(
        text(
            "DELETE FROM chips.experts e WHERE e.id = ANY(:ids) AND NOT EXISTS "
            "(SELECT 1 FROM chips.elicitation_sessions s WHERE s.expert_id = e.id)"
        ),
        {"ids": sorted(experts)},
    )

    for unit in units:
        unit.status = UnitStatus.REMOVED
        record_event(
            db,
            actor_id=actor_id,
            entity_type="knowledge_unit",
            entity_id=unit.id,
            action="unit_removed",
            from_state=UnitStatus.INGESTED.value,
            to_state=UnitStatus.REMOVED.value,
            meta={"assignment_id": str(unit.assignment_id)},
        )
    await enqueue_refit(db)
    return len(units)
