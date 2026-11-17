"""The two Ollama clients with a fake server: request bodies, error handling, normalisation."""

import json

import httpx
import numpy as np
import pytest

from app import ollama
from app.embeddings import OllamaEmbedder


@pytest.mark.parametrize(
    ("raw", "parsed"),
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ('```\n{"a": 1}\n```', {"a": 1}),
        ('  \n{"a": [1, 2]}  ', {"a": [1, 2]}),
        ("[1, 2]", None),  # valid JSON, not an object
        ('"text"', None),
        ("not json", None),
        ("", None),
        ('{"a": ', None),
    ],
)
def test_a_reply_is_a_json_object_or_none(raw, parsed):
    assert ollama.parse_json_object(raw) == parsed


def serve(monkeypatch, handler):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        ollama.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
    )


async def test_chat_json_sends_a_json_mode_request_and_returns_the_content(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"], seen["body"] = request.url.path, json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": '{"ok": true}'}})

    serve(monkeypatch, handler)
    reply = await ollama.chat_json("m", "be brief", "question", {"seed": 7})
    assert reply == '{"ok": true}' and seen["path"] == "/api/chat"
    assert seen["body"]["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "question"},
    ]
    assert seen["body"] | {"messages": None} == {
        "model": "m", "messages": None, "stream": False, "think": False, "format": "json",
        "options": {"seed": 7},
    }  # fmt: skip


async def test_chat_json_without_a_system_prompt_sends_only_the_user_message(monkeypatch):
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "{}"}})

    serve(monkeypatch, handler)
    await ollama.chat_json("m", None, "q", {})
    assert bodies[0]["messages"] == [{"role": "user", "content": "q"}]


async def test_chat_json_raises_when_the_server_does(monkeypatch):
    serve(monkeypatch, lambda request: httpx.Response(500))
    with pytest.raises(httpx.HTTPStatusError):
        await ollama.chat_json("m", None, "q", {})


def embedder(handler, **kw) -> OllamaEmbedder:
    e = OllamaEmbedder("bge-m3", base_url="http://ollama", **kw)
    e.client = httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(handler))
    return e


def test_embeddings_are_sent_in_batches_and_come_back_normalised():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(200, json={"embeddings": [[3.0, 4.0] for _ in body["input"]]})

    vectors = embedder(handler, batch_size=2, truncate=False).embed(["a", "b", "c", "d", "e"])
    assert [c["input"] for c in calls] == [["a", "b"], ["c", "d"], ["e"]]
    assert all(c["model"] == "bge-m3" and c["truncate"] is False for c in calls)
    assert vectors.shape == (5, 2) and vectors.dtype == np.float32
    assert np.allclose(vectors, [[0.6, 0.8]] * 5)


def test_a_zero_vector_stays_zero_instead_of_dividing_by_zero():
    vectors = embedder(lambda r: httpx.Response(200, json={"embeddings": [[0.0, 0.0]]})).embed(
        ["x"]
    )
    assert np.array_equal(vectors, [[0.0, 0.0]])


def test_a_missing_model_says_which_one_to_pull():
    with pytest.raises(RuntimeError, match="ollama pull bge-m3"):
        embedder(lambda r: httpx.Response(404)).embed(["x"])


def test_other_server_errors_are_raised_as_they_are():
    with pytest.raises(httpx.HTTPStatusError):
        embedder(lambda r: httpx.Response(500)).embed(["x"])
