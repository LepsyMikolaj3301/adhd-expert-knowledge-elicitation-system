"""The error shape and its message helpers (core/errors.py), without a server."""

import logging

import pytest

from app.core.errors import (
    DomainError,
    SafeErrorMiddleware,
    _field_name,
    _validation_message,
    forbidden,
    invalid,
    not_found,
    safe_traceback,
)


@pytest.mark.parametrize(
    ("loc", "name"),
    [
        (["body", "display_name"], "Display name"),
        (["body", "items", 0, "chip"], "Chip"),
        (["query", "limit"], "Limit"),
        (["body"], "The request"),
        ([], "The request"),
        ([0, 1], "The request"),
    ],
)
def test_the_field_is_the_last_named_part_of_the_location(loc, name):
    assert _field_name(loc) == name


@pytest.mark.parametrize(
    ("errors", "message"),
    [
        ([], "The request is not valid."),
        ([{"loc": ["body", "email"], "msg": "Field required"}], "Email: Field required."),
        (
            [{"loc": ["body", "email"], "msg": "Value error, bad address"}],
            "Email: bad address.",
        ),
        ([{"loc": ["body", "x"], "msg": "Really?"}], "X: Really?"),
        (
            [{"loc": ["body", "a"], "msg": "bad"}, {"loc": ["body", "b"], "msg": "worse"}],
            "A: bad. (and 1 more problem)",
        ),
        (
            [{"loc": ["body", "a"], "msg": "bad"}] * 3,
            "A: bad. (and 2 more problems)",
        ),
    ],
)
def test_a_validation_message_names_the_first_problem_and_counts_the_rest(errors, message):
    assert _validation_message(errors) == message


def test_the_domain_errors_carry_status_code_and_details():
    assert (not_found("Case").status_code, not_found("Case").details) == (404, {"resource": "Case"})
    assert not_found().message == "Resource not found."
    assert invalid("code", "msg", {"a": 1}).status_code == 422
    assert forbidden().status_code == 403 and forbidden().code == "forbidden"
    assert DomainError("c", "m").status_code == 409


SECRET = "Failing row contains (quoted expert text)"  # not in the source line that raises


def test_a_traceback_has_the_types_and_never_the_messages():
    try:
        try:
            raise ValueError(SECRET)
        except ValueError as cause:
            raise RuntimeError(SECRET.upper()) from cause
    except RuntimeError as error:
        text = safe_traceback(error)
    assert "RuntimeError" in text and "ValueError" in text
    assert "expert text" not in text.lower()


def test_a_traceback_follows_the_context_when_there_is_no_cause():
    try:
        try:
            raise KeyError(SECRET)
        except KeyError:
            raise OSError(SECRET) from None
    except OSError as error:
        error.__cause__ = None
        text = safe_traceback(error)
    assert "OSError" in text and "KeyError" in text and "expert text" not in text


def test_a_cycle_in_the_chain_ends():
    a, b = RuntimeError("a"), RuntimeError("b")
    a.__cause__, b.__cause__ = b, a
    text = safe_traceback(a)
    assert text.count("RuntimeError") == 2


async def test_the_middleware_answers_500_and_logs_without_the_message(caplog):
    sent = []

    async def app(scope, receive, send):
        raise RuntimeError(SECRET)

    async def send(message):
        sent.append(message)

    with caplog.at_level(logging.ERROR):
        await SafeErrorMiddleware(app)({"type": "http"}, None, send)
    assert sent[0]["status"] == 500
    assert "expert text" not in caplog.text and "RuntimeError" in caplog.text


async def test_the_middleware_cannot_answer_once_the_response_has_started(caplog):
    sent = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        raise RuntimeError("late")

    async def send(message):
        sent.append(message)

    with caplog.at_level(logging.ERROR):
        await SafeErrorMiddleware(app)({"type": "http"}, None, send)
    assert [m["type"] for m in sent] == ["http.response.start"]
    assert "unhandled error" in caplog.text


async def test_the_middleware_passes_other_scopes_through():
    seen = []

    async def app(scope, receive, send):
        seen.append(scope["type"])

    await SafeErrorMiddleware(app)({"type": "lifespan"}, None, None)
    assert seen == ["lifespan"]
