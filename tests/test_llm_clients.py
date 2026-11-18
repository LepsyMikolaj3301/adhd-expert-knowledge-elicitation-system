import json

import httpx
import pytest
from llm_clients import (
    AwaitingResponse,
    CachedGenerator,
    FileGenerator,
    GenRequest,
    InboxGenerator,
    ModelRefused,
    OllamaGenerator,
)


def test_inbox_writes_request_then_reads_response(tmp_path):
    gen = InboxGenerator(tmp_path)
    req = GenRequest(key="answer:V001:clean:P1", system="sys", user="the prompt")
    with pytest.raises(AwaitingResponse):
        gen.generate(req)
    request_file = tmp_path / "requests" / "answer.V001.clean.P1.md"
    assert "the prompt" in request_file.read_text()
    (tmp_path / "responses").mkdir()
    (tmp_path / "responses" / "answer.V001.clean.P1.json").write_text('{"ok": 1}')
    assert json.loads(gen.generate(req)) == {"ok": 1}


def test_file_generator_reads_by_key_and_names_its_author(tmp_path):
    (tmp_path / "persona.S01.json").write_text("{}")
    assert FileGenerator(tmp_path).name == "file"
    (tmp_path / "PROVENANCE.json").write_text('{"model": "qwen3.5:9b"}')
    gen = FileGenerator(tmp_path)
    assert (
        gen.name == "file:qwen3.5:9b"
        and gen.generate(GenRequest(key="persona:S01", user="")) == "{}"
    )
    with pytest.raises(FileNotFoundError):
        gen.generate(GenRequest(key="persona:S99", user=""))


def test_cache_stores_each_request_once(tmp_path):
    class Counting:
        name = "m"
        calls = 0

        def generate(self, req):
            self.calls += 1
            return "out"

    inner = Counting()
    gen = CachedGenerator(inner, tmp_path)
    req = GenRequest(key="k", user="u", seed=1)
    assert gen.generate(req) == gen.generate(req) == "out" and inner.calls == 1
    gen.generate(GenRequest(key="k", user="u", seed=2))  # a new seed is a new request
    assert inner.calls == 2


def ollama_with(statuses):
    """An OllamaGenerator whose server answers with the given status codes, in order."""
    calls = []

    def handler(request):
        calls.append(request)
        status = statuses[min(len(calls), len(statuses)) - 1]
        body = {"message": {"content": "hello"}} if status == 200 else {}
        return httpx.Response(status, json=body)

    gen = OllamaGenerator("http://ollama", "m")
    gen._http = httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(handler))
    gen.retry_wait = 0
    return gen, calls


def test_ollama_retries_server_errors_but_not_client_errors():
    gen, calls = ollama_with([500, 500, 200])
    assert gen.generate(GenRequest(key="k", user="u")) == "hello" and len(calls) == 3
    gen, calls = ollama_with([500])
    with pytest.raises(httpx.HTTPStatusError):  # gives up after 3 attempts
        gen.generate(GenRequest(key="k", user="u"))
    assert len(calls) == 3
    gen, calls = ollama_with([404])
    with pytest.raises(httpx.HTTPStatusError):  # a client error is not retried
        gen.generate(GenRequest(key="k", user="u"))
    assert len(calls) == 1


def test_repetition_abort_is_a_refusal_not_retried():
    def handler(request):
        return httpx.Response(500, json={"error": "prediction aborted, token repeat limit reached"})

    gen = OllamaGenerator("http://ollama", "m")
    gen._http = httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(handler))
    with pytest.raises(ModelRefused):
        gen.generate(GenRequest(key="k", user="u"))


def test_ollama_sends_think_as_configured():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "x"}})

    for think in (False, "low"):
        gen = OllamaGenerator("http://ollama", "m", think=think)
        gen._http = httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(handler))
        gen.generate(GenRequest(key="k", user="u"))
    assert [b["think"] for b in bodies] == [False, "low"]
    gen = OllamaGenerator("http://ollama", "m")  # the default is what it always was
    gen._http = httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(handler))
    gen.generate(GenRequest(key="k", user="u"))
    assert bodies[-1]["think"] is False
