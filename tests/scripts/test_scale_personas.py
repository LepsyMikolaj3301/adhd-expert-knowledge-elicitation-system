"""Tests for the persona experts (21-32) and the proofread stage of make_scale_fixtures.py,
and for the pool order of eval_scale_retrieval.py."""

import argparse
import json
from datetime import UTC, datetime

import make_scale_fixtures as msf
import pytest
from chips_schema import ChipDocument
from elicitation_schema import Vignette, VignetteDesign, content_hash
from make_fixtures import fixture_dir

TEXT = (
    "I only opened the file at nine because I did the dishes first. The report is due on Friday "
    "and I told myself two hours. The street is louder than the old one, so I woke at five."
)
MODELS = {"gpt-oss:20b", "mistral-small3.2:24b", "qwen3.8:27b"}


def vignette(vid="V001") -> Vignette:
    return Vignette(
        id=vid, version=1, text=TEXT, content_hash=content_hash(TEXT), framing="personal_journal",
        question_ids=["Q1", "Q2", "Q3", "Q5", "Q6"], design=VignetteDesign(purpose="test"),
    )  # fmt: skip


def test_persona_files_are_complete_and_different():
    systems, styles, citations = set(), set(), set()
    for e in msf.PERSONA_EXPERTS:
        p = msf.load_persona(e)
        assert p.meta["expert"] == f"E{e}" and p.meta["model"] in MODELS
        assert p.meta["role"] and p.meta["citation"] and p.system and p.user
        assert (p.meta["think"] == "low") == p.meta["model"].startswith("gpt-oss")
        systems.add(p.system)
        styles.add(p.user)
        citations.add(p.meta["citation"])
    n = len(msf.PERSONA_EXPERTS)
    assert len(systems) == len(styles) == len(citations) == n == 12
    assert {msf.load_persona(e).meta["model"] for e in msf.PERSONA_EXPERTS} == MODELS


def test_personas_reach_role_for_by_document_number():
    msf.with_scale_personas()
    from make_unit_keys import role_for

    role = role_for("silver", "DOC-SYN-0021")
    assert role.startswith("consultant psychiatrist") and "19 years" in role
    assert role_for("silver", "DOC-SYN-0032").startswith("trainee clinical psychologist")
    assert len(msf.ALL_PERSONAS) == 32


def test_persona_request_fills_v5_with_the_experts_own_text():
    v = vignette()
    req, model, think = msf.persona_request(v, 21)
    persona = msf.load_persona(21)
    assert req.key == "answer:V001:persona:E21" and model == "gpt-oss:20b" and think == "low"
    assert persona.system in req.system and persona.user in req.user and TEXT in req.user
    assert "{{" not in req.system + req.user
    assert req.options["num_predict"] > 3000  # a thinking model needs room before the JSON
    _, model, think = msf.persona_request(v, 26)
    assert model == "mistral-small3.2:24b" and think is False  # `none` in the file


def test_every_vignette_gets_enough_experts_with_the_new_ones():
    vignettes = [f"V{i:03d}" for i in range(1, 25)]
    per_vignette = dict.fromkeys(vignettes, 0)
    for e in range(3, msf.LAST_EXPERT + 1):
        mine = msf.rotation(e, vignettes, 1)
        assert set(msf.ANCHORS) <= set(mine)
        for v in mine:
            per_vignette[v] += 1
    assert all(per_vignette[a] == 30 for a in msf.ANCHORS)
    assert min(per_vignette.values()) >= 4


# --- the proofread stage ---------------------------------------------------------------------


def doc_with(answers: dict[str, str]) -> ChipDocument:
    t = datetime(2026, 1, 5, 9, tzinfo=UTC)
    frag = "I only opened the file at nine"
    highlights = [dict(chip=1, text=frag, span=[0, len(frag) + 2], direction="toward")]
    highlights[0]["span"] = [TEXT.index(frag), TEXT.index(frag) + len(frag)]
    v = vignette()
    resp = dict(
        vignette_id="V001", vignette_version=1, vignette_hash=v.content_hash, expert_id="SYN-003",
        answers=answers, highlights=highlights, rating=3, started_at=t,
        submitted_at=t, insufficient_information=False,
    )  # fmt: skip
    return ChipDocument(
        session_id="DOC-SYN-0003", expert_id="SYN-003", created_at=t,
        vignettes=[v], responses=[resp],
    )  # fmt: skip


def setup_raw(tmp_path, answers):
    raw = fixture_dir(msf.TIER, "synthetic", tmp_path / "raw")
    for folder in ("vignettes", "documents", "claims"):
        (raw / folder).mkdir(parents=True)
    doc = doc_with(answers)
    (raw / "documents" / "DOC-SYN-0003.json").write_text(doc.model_dump_json())
    (raw / "vignettes" / "V001.json").write_text(doc.vignettes[0].model_dump_json())
    (raw / "claims" / "DOC-SYN-0003.claims.json").write_text("[]")
    (raw / "manifest.json").write_text(json.dumps({"tier": "silver"}))
    return tmp_path / "raw", tmp_path / "proofread"


def args_for(raw, out) -> argparse.Namespace:
    return argparse.Namespace(out=raw, proofread_out=out)


@pytest.fixture
def fake_pipeline(monkeypatch):
    from app.proofread import pipeline

    calls = []

    async def fake(question, answer, quotes, vignette):
        calls.append((question, answer, quotes))
        return pipeline.Proofread(
            text=answer.replace(" i ", " I ").replace(". ", ".\n"),
            dropped=[],
            passes={"grammar": 1, "languagetool": "6.8"},
        )

    monkeypatch.setattr(pipeline, "proofread_answer", fake)
    monkeypatch.setattr(msf, "preflight_proofread", lambda: None)
    return calls


def test_proofread_stage_writes_proofread_answers_and_a_sidecar(tmp_path, fake_pipeline):
    answers = {
        "Q1": "⟦h1⟧ is a late start. then i sleep.",
        "Q2": "Sleep ⟦h1⟧.",
        "Q3": "Ask more.",
        "Q5": "Rare.",
    }
    raw, out = setup_raw(tmp_path, answers)
    assert msf.proofread_stage(args_for(raw, out)) == 0
    dst = fixture_dir(msf.TIER, "synthetic", out)
    doc = ChipDocument.model_validate_json((dst / "documents" / "DOC-SYN-0003.json").read_text())
    assert doc.responses[0].answers["Q1"] == "⟦h1⟧ is a late start.\nthen I sleep."
    assert doc.responses[0].highlights[0].text == "I only opened the file at nine"
    side = json.loads((dst / "proofread" / "DOC-SYN-0003.json").read_text())
    assert side["V001"]["Q1"]["original"] == answers["Q1"]
    assert (dst / "vignettes" / "V001.json").exists() and (dst / "claims").is_dir()
    manifest = json.loads((dst / "manifest.json").read_text())
    assert manifest["proofread"]["languagetool"] == ["6.8"]
    assert fake_pipeline[0][2] == {1: "I only opened the file at nine"}  # the quotes of the chips


def test_proofread_stage_resumes_and_stops_on_lost_chips(tmp_path, fake_pipeline, monkeypatch):
    raw, out = setup_raw(tmp_path, {"Q1": "⟦h1⟧ a. b.", "Q2": "⟦h1⟧ c.", "Q3": "d.", "Q5": "e."})
    msf.proofread_stage(args_for(raw, out))
    n = len(fake_pipeline)
    msf.proofread_stage(args_for(raw, out))
    assert len(fake_pipeline) == n  # the document is done: nothing is proofread again

    from app.proofread import pipeline

    async def drops_chip(question, answer, quotes, vignette):
        return pipeline.Proofread(text="no chip left")

    monkeypatch.setattr(pipeline, "proofread_answer", drops_chip)
    raw, out = setup_raw(
        tmp_path / "again", {"Q1": "⟦h1⟧ a.", "Q2": "⟦h1⟧ b.", "Q3": "c.", "Q5": "d."}
    )
    with pytest.raises(SystemExit, match="chips changed"):
        msf.proofread_stage(args_for(raw, out))


# --- the pool order of the eval --------------------------------------------------------------


def test_pool_at_follows_the_schema_or_the_given_order():
    from eval_scale_retrieval import pool_at

    experts = [f"silver/SYN-{n:03d}" for n in range(1, 6)]
    assert pool_at(experts, 2, None) == experts[:2]
    assert pool_at(experts, 3, [1, 5, 4, 2]) == [experts[0], experts[4], experts[3]]
    with pytest.raises(ValueError, match="not in the schema"):
        pool_at(experts, 2, [1, 9])


def test_repair_mends_harmless_slips_only():
    data = {
        "gold_claims": [
            {"question_id": "Q1", "claim": "c", "quoted_span_text": "null", "direction": "toward"},
            {"question_id": "Q1", "claim": "c", "quoted_span_text": "real", "direction": "unclear"},
            {
                "question_id": "Q6",
                "claim": "rating",
                "quoted_span_text": None,
                "direction": "raises",
            },
        ],
        "highlights": [{"chip": 1, "text": "not in the text"}],
    }
    out = msf.repair(data)
    assert [(c["quoted_span_text"], c["direction"]) for c in out["gold_claims"]] == [
        (None, "raises"),
        ("real", "neutral"),
    ]
    assert out["highlights"] == data["highlights"]  # never mended
    assert msf.repair({"answers": {}}) == {"answers": {}}


def test_repair_mends_quote_marks_and_apostrophes_but_never_invents():
    vignette = "He said I can\u2019t start and left. Then it rained."
    assert msf.mend_highlight("\u201cI can\u2019t start\u201d", vignette) == "I can\u2019t start"
    assert msf.mend_highlight("I can't start", vignette) == "I can\u2019t start"
    assert msf.mend_highlight("it rained;", vignette) == "it rained"
    assert msf.mend_highlight("He said", vignette) == "He said"  # already exact: untouched
    assert msf.mend_highlight("it never rained", vignette) == "it never rained"
    data = {"highlights": [{"chip": 1, "text": '"Then it rained"'}, {"chip": 2, "text": "made up"}]}
    out = msf.repair(data, vignette)
    assert [h["text"] for h in out["highlights"]] == ["Then it rained", "made up"]
    assert msf.repair(data)["highlights"] == data["highlights"]  # no vignette, no mending


def test_a_lost_contraction_snaps_to_the_real_words_but_other_text_does_not():
    vignette = (
        "The date was wrong. I'd allowed an hour to check the proofs and it took nearer three, so."
    )
    got = msf.mend_highlight(
        "I allowed an hour to check the proofs and it took nearer three", vignette
    )
    assert got == "I'd allowed an hour to check the proofs and it took nearer three"
    assert got in vignette
    assert msf.mend_highlight("I never checked anything at all that day", vignette) == (
        "I never checked anything at all that day"
    )


def test_a_persona_can_set_a_repeat_penalty():
    v = vignette()
    assert msf.persona_request(v, 27)[0].options["repeat_penalty"] == 1.15
    assert "repeat_penalty" not in msf.persona_request(v, 26)[0].options


# --- the export of all answers ---------------------------------------------------------------


def test_export_joins_raw_proofread_claims_and_writer(tmp_path, fake_pipeline):
    from export_scale_answers import export

    answers = {
        "Q1": "⟦h1⟧ is a late start. then i sleep.",
        "Q2": "Sleep ⟦h1⟧.",
        "Q3": "Ask.",
        "Q5": "Rare.",
    }
    raw, out = setup_raw(tmp_path, answers)
    raw_dir = fixture_dir(msf.TIER, "synthetic", raw)
    (raw_dir / "manifest.json").write_text(
        json.dumps({"tier": "silver", "answer_models": {"SYN-003": "qwen3.8:27b"}})
    )
    claim = {"vignette_id": "V001", "question_id": "Q1", "claim_text": "starts late"}
    other = dict(claim, vignette_id="V002")
    (raw_dir / "claims" / "DOC-SYN-0003.claims.json").write_text(json.dumps([claim, other]))
    msf.proofread_stage(args_for(raw, out))

    data = export(raw, out)
    assert list(data["experts"]) == ["SYN-003"] and list(data["vignettes"]) == ["V001"]
    assert data["experts"]["SYN-003"]["model"] == "qwen3.8:27b"
    assert data["experts"]["SYN-003"]["persona_id"] == "E03"
    (r,) = data["responses"]
    assert r["answers_raw"] == answers
    assert r["answers_proofread"]["Q1"] == "⟦h1⟧ is a late start.\nthen I sleep."
    assert r["claims"] == [claim]  # only the claims of this vignette
    assert r["proofread"]["Q1"]["passes"]["languagetool"] == "6.8"
    assert r["highlights"][0]["chip"] == 1 and r["rating"] == 3
