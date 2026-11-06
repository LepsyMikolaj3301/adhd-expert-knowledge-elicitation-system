"""Who may read a submission under review.

Every active expert may, except the author and anyone who still has to answer the vignette
themselves: reading a colleague's answers would colour their own. The rule is checked when someone
asks, not decided once when the units are cut, so an expert who joins later sees the review too.

Reading is explicit. A reviewer opens a review (`POST /assignments/{id}/review/open`) before any of
its text is sent, and that is recorded in `review_participants`: from then on they can't be
assigned that vignette.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assignments.models import Assignment
from app.assignments.states import State
from app.reviews.models import ReviewParticipant
from app.users.models import Role, User
from app.vignettes.models import VignetteVersion

PRE_SUBMISSION_STATES = (State.ASSIGNED, State.IN_PROGRESS)
# Discussion and votes happen while a review is open; the rest can still be read.
OPEN_REVIEW_STATES = frozenset({State.PEER_REVIEW})
CLOSED_REVIEW_STATES = frozenset(
    {State.INGESTING, State.INGESTION_FAILED, State.INGESTED, State.REJECTED}
)
REVIEW_VISIBLE_STATES = OPEN_REVIEW_STATES | CLOSED_REVIEW_STATES


async def blocked_vignettes(db: AsyncSession, expert_id: UUID) -> set[UUID]:
    """The vignettes the expert still has to answer, on any version: theirs to read last."""
    rows = await db.scalars(
        select(VignetteVersion.vignette_id)
        .join(Assignment, Assignment.vignette_version_id == VignetteVersion.id)
        .where(Assignment.expert_id == expert_id, Assignment.state.in_(PRE_SUBMISSION_STATES))
        .distinct()
    )
    return set(rows)


async def vignette_id_of(db: AsyncSession, assignment: Assignment) -> UUID:
    vignette_id = await db.scalar(
        select(VignetteVersion.vignette_id).where(
            VignetteVersion.id == assignment.vignette_version_id
        )
    )
    assert vignette_id is not None
    return vignette_id


async def has_opened(db: AsyncSession, assignment_id: UUID, expert_id: UUID) -> bool:
    found = await db.scalar(
        select(ReviewParticipant.expert_id).where(
            ReviewParticipant.assignment_id == assignment_id,
            ReviewParticipant.expert_id == expert_id,
        )
    )
    return found is not None


async def may_review(db: AsyncSession, assignment: Assignment, viewer: User) -> bool:
    """Whether the viewer, who is not the author or an admin, is a reviewer of this assignment."""
    if viewer.role != Role.EXPERT or not viewer.is_active:
        return False
    if await has_opened(db, assignment.id, viewer.id):
        return True
    if assignment.state not in REVIEW_VISIBLE_STATES:
        return False
    return await vignette_id_of(db, assignment) not in await blocked_vignettes(db, viewer.id)
