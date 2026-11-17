"""The job tables must cover every kind of job, or a queued job would crash the worker."""

from app.assignments.states import Action
from app.jobs import handlers, worker
from app.jobs.models import JobKind


def test_every_job_kind_has_a_handler():
    assert set(handlers.HANDLERS) | set(handlers.CORPUS_HANDLERS) == set(JobKind)
    assert not set(handlers.HANDLERS) & set(handlers.CORPUS_HANDLERS)


def test_only_jobs_with_a_slow_part_are_prepared_and_each_has_a_handler():
    assert set(handlers.PREPARE) == {JobKind.PROOFREAD, JobKind.INGEST}
    assert set(handlers.PREPARE) <= set(handlers.HANDLERS)


def test_every_assignment_job_moves_the_workflow_on_success_and_on_failure():
    assignment_jobs = set(handlers.HANDLERS)
    assert set(worker.SUCCESS_ACTION) == set(worker.FAILURE_ACTION) == assignment_jobs
    assert all(action in Action for action in worker.SUCCESS_ACTION.values())
    assert len(
        set(worker.SUCCESS_ACTION.values()) | set(worker.FAILURE_ACTION.values())
    ) == 2 * len(assignment_jobs)


def test_a_unit_hash_covers_both_embedded_texts():
    base = handlers.unit_content_hash("i1", "i3")
    assert base == handlers.unit_content_hash("i1", "i3")
    assert base != handlers.unit_content_hash("i1", "other i3")
    assert base != handlers.unit_content_hash("other i1", "i3")
