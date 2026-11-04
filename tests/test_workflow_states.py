"""The transition table, checked exhaustively against the agreed workflow, written out by hand."""

import subprocess
import sys
from itertools import product
from pathlib import Path

import pytest
from fastapi import status

from app.assignments.state_machine import JOB_ON_ENTRY, TRANSITIONS, check_transition, user_actions
from app.assignments.states import JOB_STATES, TERMINAL_STATES, Action, Actor, State
from app.core.errors import DomainError
from app.jobs.models import JobKind

EXPECTED_TABLES = 13
A, E, R, S = Actor.ADMIN, Actor.ASSIGNEE, Actor.REVIEWER, Actor.SYSTEM

WORKFLOW = {
    (State.ASSIGNED, Action.START): (State.IN_PROGRESS, {E}),
    (State.ASSIGNED, Action.CANCEL): (State.CANCELLED, {A}),
    (State.IN_PROGRESS, Action.CANCEL): (State.CANCELLED, {A}),
    (State.IN_PROGRESS, Action.SUBMIT): (State.PROCESSING, {E}),
    (State.PROCESSING, Action.PROCESSING_SUCCEEDED): (State.EXPERT_CHECK, {S}),
    (State.PROCESSING, Action.PROCESSING_FAILED): (State.PROCESSING_FAILED, {S}),
    (State.EXPERT_CHECK, Action.COMPLETE_EXPERT_CHECK): (State.BUILDING_UNITS, {E}),
    (State.EXPERT_CHECK, Action.SKIP_EXPERT_CHECK): (State.BUILDING_UNITS, {E, A}),
    (State.BUILDING_UNITS, Action.UNITS_BUILT): (State.ADMIN_REVIEW, {S}),
    (State.BUILDING_UNITS, Action.UNITS_FAILED): (State.PROCESSING_FAILED, {S}),
    (State.PROCESSING_FAILED, Action.RETRY_PROCESSING): (State.PROCESSING, {A}),
    (State.PROCESSING_FAILED, Action.RETRY_UNITS): (State.BUILDING_UNITS, {A}),
    (State.ADMIN_REVIEW, Action.APPROVE_UNITS): (State.INGESTING, {A}),
    (State.ADMIN_REVIEW, Action.REJECT_ALL_UNITS): (State.REJECTED, {A}),
    (State.ADMIN_REVIEW, Action.REQUEST_PEERS): (State.PEER_REVIEW, {A}),
    (State.PEER_REVIEW, Action.PEERS_APPROVED): (State.INGESTING, {R}),
    (State.PEER_REVIEW, Action.PEER_REJECTED): (State.ADMIN_REVIEW, {R}),
    (State.PEER_REVIEW, Action.RECALL_REVIEW): (State.ADMIN_REVIEW, {A}),
    (State.INGESTING, Action.INGESTION_SUCCEEDED): (State.INGESTED, {S}),
    (State.INGESTING, Action.INGESTION_FAILED): (State.INGESTION_FAILED, {S}),
    (State.INGESTION_FAILED, Action.RETRY_INGESTION): (State.INGESTING, {A}),
}


@pytest.mark.parametrize(("state", "action", "actor"), list(product(State, Action, Actor)))
def test_every_combination(state, action, actor):
    expected = WORKFLOW.get((state, action))
    if expected is None:
        with pytest.raises(DomainError) as error:
            check_transition(state, action, actor)
        assert error.value.code == "illegal_transition"
        assert error.value.status_code == status.HTTP_409_CONFLICT
    elif actor in expected[1]:
        assert check_transition(state, action, actor).to == expected[0]
    else:
        with pytest.raises(DomainError) as error:
            check_transition(state, action, actor)
        assert error.value.code == "forbidden"
        assert error.value.status_code == status.HTTP_403_FORBIDDEN


def test_table_has_no_extra_rules():
    assert set(TRANSITIONS) == set(WORKFLOW)


def test_terminal_states_have_no_way_out():
    assert {State.INGESTED, State.REJECTED, State.CANCELLED} == TERMINAL_STATES
    assert not [key for key in TRANSITIONS if key[0] in TERMINAL_STATES]


def test_every_state_is_reachable_and_non_terminal_states_can_move():
    targets = {rule.to for rule in TRANSITIONS.values()} | {State.ASSIGNED}
    assert targets == set(State)
    assert {state for state, _ in TRANSITIONS} == set(State) - TERMINAL_STATES


def test_answers_can_never_reopen():
    """Agreed: nothing leads back to answering once submitted."""
    entering = [key for key, rule in TRANSITIONS.items() if rule.to == State.IN_PROGRESS]
    assert entering == [(State.ASSIGNED, Action.START)]


def test_every_job_state_queues_its_job():
    assert JOB_ON_ENTRY == {
        State.PROCESSING: JobKind.PROCESS,
        State.BUILDING_UNITS: JobKind.BUILD_UNITS,
        State.INGESTING: JobKind.INGEST,
    }
    assert set(JOB_ON_ENTRY) == JOB_STATES


def test_the_system_has_no_user_actions():
    assert not any(user_actions(state, S) for state in State)


def test_user_action_names_per_role():
    assert user_actions(State.EXPERT_CHECK, E) == {"complete_expert_check", "skip_expert_check"}
    assert user_actions(State.EXPERT_CHECK, A) == {"skip_expert_check"}
    assert user_actions(State.ADMIN_REVIEW, A) == {"decide_units", "request_peers"}
    assert user_actions(State.PEER_REVIEW, A) == {"recall_review"}
    assert user_actions(State.PEER_REVIEW, R) == {"decide_units"}
    assert user_actions(State.PROCESSING_FAILED, A) == {"retry"}


@pytest.mark.parametrize("module", ["app.jobs.worker", "app.cli", "app.main"])
def test_each_entry_point_knows_every_table_on_its_own(module):
    """Each runs as its own process, so one can't rely on another having imported the models."""
    code = (
        f"import {module}\nfrom app.core.db import Base\nprint(len(Base.metadata.sorted_tables))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).resolve().parents[1] / "backend",
    )
    assert result.returncode == 0, result.stderr
    assert int(result.stdout) == EXPECTED_TABLES
