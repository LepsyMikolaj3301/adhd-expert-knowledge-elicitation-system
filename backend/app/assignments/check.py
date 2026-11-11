"""How the approved answers were filed: their sentences under citations, as cut into units.

The admin's window into the silent part of the pipeline. The author links lines in the proofread
check (app.proofread) and never sees this.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.assignments.models import Assignment
from app.assignments.schemas import FindingFlag, FindingHighlight, FindingSentence, FindingsView
from app.assignments.states import Actor
from app.core.errors import not_found
from app.knowledge import findings
from app.knowledge.models import AnswerFindings


async def get(db: AsyncSession, assignment: Assignment, actor: Actor) -> FindingsView:
    if actor != Actor.ADMIN:
        raise not_found("Findings")
    row = await db.get(AnswerFindings, assignment.id)
    if row is None:
        raise not_found("Findings")
    record = row.record
    return FindingsView(
        version=row.version,
        review_round=assignment.review_round,
        check_outcome=row.check_outcome,  # ty: ignore[invalid-argument-type]
        highlights=[
            FindingHighlight(
                id=h["id"],
                chip=h["chip"],
                text=h["text"],
                origin=h["origin"],
                direction=h["direction"],
            )
            for h in record["highlights"]
        ],
        sentences=[
            FindingSentence(
                id=s["id"],
                question_id=s["question_id"],
                text=findings.render_sentence(s["text"], record["highlights"]),
                targets=s["targets"],
                assigned_by=s["assigned_by"],
            )
            for s in record["sentences"]
        ],
        flags=[
            FindingFlag(
                kind=f["kind"],
                highlight=f["highlight"],
                sentence=f.get("sentence"),
                message=f["message"],
            )
            for f in record["flags"]
        ],
    )
