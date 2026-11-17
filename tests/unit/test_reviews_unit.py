"""Who a line of the review discussion is from, as the viewer may know it (reviews/service.py)."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.assignments.states import Actor
from app.reviews.service import speaker_for
from app.users.models import Role

AUTHOR, OTHER = uuid4(), uuid4()
ASSIGNMENT = SimpleNamespace(expert_id=AUTHOR)


@pytest.mark.parametrize(
    ("user_id", "role", "actor", "kind", "shows_name"),
    [
        # the author is never named to a peer or to themselves, only to an admin
        (AUTHOR, Role.EXPERT, Actor.ASSIGNEE, "author", False),
        (AUTHOR, Role.EXPERT, Actor.REVIEWER, "author", False),
        (AUTHOR, Role.EXPERT, Actor.ADMIN, "author", True),
        # an admin is a role, not a person
        (OTHER, Role.ADMIN, Actor.ADMIN, "admin", True),
        (OTHER, Role.ADMIN, Actor.REVIEWER, "admin", False),
        # a reviewer is always shown by pseudonym
        (OTHER, Role.EXPERT, Actor.REVIEWER, "reviewer", True),
        (OTHER, Role.EXPERT, Actor.ASSIGNEE, "reviewer", True),
        (OTHER, Role.EXPERT, Actor.ADMIN, "reviewer", True),
    ],
)
def test_the_viewer_sees_a_pseudonym_only_where_the_rules_allow(
    user_id, role, actor, kind, shows_name
):
    speaker = speaker_for(ASSIGNMENT, actor, user_id=user_id, role=role, pseudonym="Falcon")
    assert speaker.kind == kind
    assert speaker.pseudonym == ("Falcon" if shows_name else None)


def test_the_author_who_is_also_an_admin_is_still_the_author():
    speaker = speaker_for(
        ASSIGNMENT, Actor.ASSIGNEE, user_id=AUTHOR, role=Role.ADMIN, pseudonym="X"
    )
    assert speaker.kind == "author"
