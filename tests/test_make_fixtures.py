"""The generator end to end with a fake model: no network, no Ollama."""

import json
from typing import Any

import make_fixtures
from elicitation_schema import ElicitationDocument, Vignette
from llm_clients import GenRequest

CUE = "tomorrow turns into the next week"
FAKE_VIGNETTE: dict[str, Any] = {
    "text": make_fixtures.EDGE_TEXT,
    "planted_cues": [{"quote": CUE, "trait": "task_initiation", "strength": "moderate"}],
    "confounders": [
        {"quote": "the new place is loud so I wake up at five", "alternative_explanation": "sleep"}
    ],
}


class FakeGenerator:
    name = "fake"

    def __init__(self):
        self.calls: list[str] = []

    def generate(self, req: GenRequest) -> str:
        self.calls.append(req.key)
        if req.key.startswith("persona:"):
            return json.dumps(FAKE_VIGNETTE)
        kind = req.key.split(":")[2]
        q1 = f"'{CUE}' suggests initiation trouble."
        insufficient = kind == "insufficient_info"
        return json.dumps(
            {
                "answers": {q: f"answer {q}" for q in ("Q2", "Q3", "Q4", "Q5")} | {"Q1": q1},
                "overall_rating": None if insufficient else 3,
                "insufficient_information": insufficient,
                "gold_claims": [
                    {
                        "claim": "initiation",
                        "quoted_span_text": CUE,
                        "trait": "task_initiation",
                        "condition": None,
                        "direction": "raises",
                    }
                ],
            }
        )


def run(tmp_path, seed="1"):
    gen = FakeGenerator()
    out = tmp_path / "out"
    code = make_fixtures.main(
        [
            "--out",
            str(out),
            "--seed",
            seed,
            "--persona-source",
            "ollama",
            "--answer-source",
            "ollama",
        ],
        persona_gen=gen,
        answer_gen=gen,
    )
    assert code == 0
    return out, gen


def test_generates_valid_reproducible_set(tmp_path):
    out, gen = run(tmp_path / "a")
    docs = sorted((out / "synthetic" / "bronze" / "documents").glob("*.json"))
    assert len(docs) == 3
    for path in docs:
        doc = ElicitationDocument.model_validate_json(path.read_text())
        assert doc.is_synthetic and doc.expert_id.startswith("SYN-")
    assert all(
        (out / "synthetic" / "bronze" / "claims" / f"{p.stem}.claims.json").exists() for p in docs
    )
    out2, _ = run(tmp_path / "b")
    for path in sorted(out.rglob("*.json")):
        assert path.read_text() == (out2 / path.relative_to(out)).read_text()


def test_dry_run_makes_no_calls(tmp_path, capsys):
    gen = FakeGenerator()
    code = make_fixtures.main(
        ["--dry-run", "--out", str(tmp_path)], persona_gen=gen, answer_gen=gen
    )
    assert code == 0 and gen.calls == [] and not list(tmp_path.iterdir())


def test_leaky_vignette_is_rejected(tmp_path):
    class Leaky(FakeGenerator):
        def generate(self, req):
            if req.key.startswith("persona:"):
                return json.dumps(
                    {**FAKE_VIGNETTE, "text": FAKE_VIGNETTE["text"] + " I have ADHD."}
                )
            return super().generate(req)

    gen = Leaky()
    code = make_fixtures.main(
        ["--out", str(tmp_path / "o"), "--persona-source", "ollama", "--retries", "1"],
        persona_gen=gen,
        answer_gen=gen,
    )
    assert code == 1


def test_ngram_copy_detected():
    shot = "one two three four five six seven eight nine ten"
    assert make_fixtures.ngrams(
        "zero one two three four five six seven eight", 8
    ) & make_fixtures.ngrams(shot, 8)
    assert not make_fixtures.ngrams("one two three four five six seven", 8)


def test_text_analysis_track_and_tier_manifest(tmp_path):
    out, _ = run(tmp_path)
    manifest = json.loads((out / "synthetic" / "bronze" / "manifest.json").read_text())
    assert manifest["tier"] == "bronze" and "plumbing" in manifest["quality"]
    assert all(e["tier"] == "bronze" for e in manifest["entries"])
    tracks = {
        json.loads(p.read_text())["design"]["track"]
        for p in (out / "synthetic" / "bronze" / "vignettes").glob("V*.json")
    }
    assert tracks == {"general", "text_analysis"}


def test_tier_rules(tmp_path):
    import pytest

    gen = FakeGenerator()
    base = ["--out", str(tmp_path), "--persona-source", "ollama"]
    for tier, answer_source in (("gold", "ollama"), ("silver", "ollama"), ("bronze", "claude")):
        with pytest.raises(SystemExit):
            make_fixtures.main(
                [*base, "--answer-source", answer_source, "--tier", tier],
                persona_gen=gen,
                answer_gen=gen,
            )


def answer_json(**override):
    data = {
        "answers": {q: f"answer {q}" for q in ("Q1", "Q2", "Q3", "Q4", "Q5")},
        "overall_rating": 3,
        "insufficient_information": False,
        "gold_claims": [{"claim": "c", "quoted_span_text": CUE, "trait": "t"}],
        "q4": {"hypothesis": "h", "shift": 1, "toward": "less_adhd", "other_explanation": None},
    }
    return {**data, **override}


def test_odd_model_output_is_rejected_not_a_crash():
    import pytest

    v = Vignette.model_validate(
        make_fixtures.edge_cases()["empty_answer"]["document"]["vignettes"][0]
    )
    for bad in (
        {"gold_claims": ["just a string"]},
        {"gold_claims": {"claim": "x"}},
        {"overall_rating": True},
        {"overall_rating": "3"},
        {"gold_claims": [{"claim": "x", "quoted_span_text": "not in the text"}]},
        {"q4": None},  # Q4 was asked
        {"q4": {"shift": True}},
        {"q4": {"shift": "1"}},
        {"q4": {"shift": 5}},
        {"q4": {"shift": -1, "toward": "more_adhd"}},
    ):
        with pytest.raises(make_fixtures.Rejected):
            make_fixtures.answer_pieces(answer_json(**bad), v, "clean")
    answers, *_, q4 = make_fixtures.answer_pieces(answer_json(), v, "clean")
    assert answers == {"Q1": "answer Q1", "Q4": "answer Q4"} and q4.shift == 1
    answers, *_, q4 = make_fixtures.answer_pieces(answer_json(q4={"shift": 0}), v, "clean")
    assert "Q4" not in answers and q4.shift == 0  # a why only goes with a change


def test_q4_whatif_comes_from_the_author_only():
    import pytest

    assert make_fixtures.q4_whatif_from({"q4_whatif": " the writer had an exam "}) == (
        "the writer had an exam"
    )
    assert make_fixtures.q4_whatif_from({"q4_fragment": "old style"}) is None
    assert make_fixtures.question_ids(None) == ["Q1", "Q2", "Q3", "Q5", "Q6"]
    with pytest.raises(make_fixtures.Rejected):
        make_fixtures.q4_whatif_from({"q4_whatif": "  "})


def test_variant_b_must_differ_from_a():
    import pytest

    text = make_fixtures.EDGE_TEXT
    with pytest.raises(make_fixtures.Rejected, match="identical"):
        make_fixtures.check_variant(text, text)
    with pytest.raises(make_fixtures.Rejected, match="rewrite"):
        make_fixtures.check_variant(text, "something else entirely " * 40)
    make_fixtures.check_variant(text, text.replace(" Anyway the deadline is Friday.", ""))


def test_generated_pairs_differ(tmp_path):
    out, _ = run(tmp_path)
    by_arm = {}
    for path in (out / "synthetic" / "bronze" / "vignettes").glob("V*.json"):
        v = json.loads(path.read_text())
        if v["variant"]:
            by_arm[v["variant"]["arm"]] = v["text"]
    assert set(by_arm) == {"A", "B"} and by_arm["A"] != by_arm["B"]


def test_bad_quote_is_injected_in_code(tmp_path):
    out, gen = run(tmp_path)
    assert any(":bad_quote:" in key for key in gen.calls)
    found = 0
    for path in (out / "synthetic" / "bronze" / "documents").glob("DOC-*.json"):
        doc = ElicitationDocument.model_validate_json(path.read_text())
        text = doc.vignettes[0].text
        for r in doc.responses:
            q1 = r.answers.get("Q1", "")
            if "tomorrow turns into next week" in q1:  # the CUE with its middle word dropped
                found += 1
                assert "tomorrow turns into next week" not in text  # really not in the vignette
                assert CUE in r.quoted_fragments  # the platform-marked span stays exact
    assert found >= 1


def test_local_source_and_small_pool(tmp_path):
    import pytest

    class RawFake(FakeGenerator):
        def generate(self, req):
            self.calls.append(req.key)
            assert req.raw and "=== ENTRY 4 ===" in req.user
            return make_fixtures.EDGE_TEXT

    def pool_file(n):
        rows = [
            {"label": lab, "text": f"unrelated words {i} " * 30}
            for lab in ("adhd", "control")
            for i in range(n)
        ]
        path = tmp_path / f"pool{n}.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows))
        return path

    args = ["--persona-source", "local", "--answer-source", "ollama", "--n-documents", "1"]
    out = tmp_path / "out"
    code = make_fixtures.main(
        [*args, "--out", str(out), "--seed-pool", str(pool_file(5))],
        persona_gen=RawFake(),
        answer_gen=FakeGenerator(),
    )
    assert code == 0 and list((out / "synthetic" / "bronze" / "vignettes").glob("V*.json"))
    with pytest.raises(SystemExit, match="need 3"):
        make_fixtures.main(
            [*args, "--out", str(tmp_path / "o2"), "--seed-pool", str(pool_file(2))],
            persona_gen=RawFake(),
            answer_gen=FakeGenerator(),
        )

    class Copier(RawFake):  # regurgitates a few-shot example: must be rejected
        def generate(self, req):
            return "unrelated words 0 " * 30

    code = make_fixtures.main(
        [*args, "--retries", "0", "--out", str(tmp_path / "o3"), "--seed-pool", str(pool_file(5))],
        persona_gen=Copier(),
        answer_gen=FakeGenerator(),
    )
    assert code == 1


def test_model_refusal_is_retried_with_the_next_seed(tmp_path):
    from llm_clients import ModelRefused

    class LoopsOnce(FakeGenerator):
        def generate(self, req):
            if req.key.startswith("answer:V001:") and req.seed == 1:
                raise ModelRefused("token repeat limit reached")
            return super().generate(req)

    gen = LoopsOnce()
    out = tmp_path / "out"
    code = make_fixtures.main(
        ["--out", str(out), "--persona-source", "ollama", "--answer-source", "ollama"]
        + ["--n-documents", "1"],
        persona_gen=gen,
        answer_gen=gen,
    )
    assert code == 0
    manifest = json.loads((out / "synthetic" / "bronze" / "manifest.json").read_text())
    assert any("repeat limit" in line for line in manifest["rejections"])
    assert manifest["skipped"] == []
