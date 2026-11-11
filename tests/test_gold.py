"""Gold tier helpers: answer capture, agent-written claims, human ratings. No model, no terminal."""

import json
from datetime import UTC, datetime

import pytest
from answer_vignettes import build_document, next_session_id, quoted_fragments
from chat_expert import (
    human_pass,
    judged_question,
    judgment_row,
    parse_numbers,
    parse_scores,
    siblings,
)
from eval_expert_generation import load_judgments
from make_fixtures import Rejected
from make_gold_claims import answers_block, check_claims
from rag_common import parse_sample_judgment

from app.elicitation.schema import (
    ElicitationDocument,
    QuestionId,
    Response,
    VariantInfo,
    Vignette,
    VignetteDesign,
    content_hash,
)

TEXT = (
    "I kept forgetting to draft this email all week. The deadline is Friday and the numbers "
    "keep swimming when I blink. Anyway I will try again tomorrow."
)
NOW = datetime(2026, 11, 2, tzinfo=UTC)


WHATIF = "the writer had an exam earlier that day"


def vignette(
    vid="V001", variant=None, question_ids: tuple[QuestionId, ...] = ("Q1", "Q2", "Q6")
) -> Vignette:
    return Vignette(
        id=vid, version=1, text=TEXT, content_hash=content_hash(TEXT), framing="email",
        variant=variant,
        question_ids=list(question_ids), design=VignetteDesign(purpose="test"),
        q4_whatif=WHATIF if "Q4" in question_ids else None,
    )  # fmt: skip


def draft(expert_id="E01", **entry) -> dict:
    return {
        "expert_id": expert_id,
        "order": ["V001"],
        "skipped": [],
        "answers": {
            "V001": {
                "started_at": "2026-11-02T10:00:00+00:00",
                "submitted_at": "2026-11-02T10:05:00+00:00",
                "done": True,
                "answers": {
                    "Q1": 'The "numbers keep swimming" line is not attention, more likely eyes.',
                    "Q2": "Tired eyes after a long week.",
                    "Q3": "",
                },
                "rating": 2,
                "insufficient": False,
                **entry,
            }
        },
    }


# --- answers -----------------------------------------------------------------------------------


def test_quoted_fragments_exact_pieces_and_misses():
    answers = {
        "Q1": 'Look at "kept forgetting to draft this email" and "the numbers ... when I blink", '
        'also "something the patient never wrote at all".',
        "Q2": 'Again "kept forgetting to draft this email".',
    }
    found, missing = quoted_fragments(answers, TEXT)
    assert found == ["kept forgetting to draft this email", "the numbers", "when I blink"]
    assert missing == ["something the patient never wrote at all"]


def test_build_document_is_valid_and_not_synthetic():
    doc = build_document(draft(), {"V001": vignette()}, "DOC-0001", NOW)
    assert isinstance(doc, ElicitationDocument)
    assert doc.is_synthetic is False
    (r,) = doc.responses
    written = draft()["answers"]["V001"]["answers"]
    assert r.answers == {"Q1": written["Q1"], "Q2": written["Q2"]}  # blank Q3 (not asked) dropped
    assert r.quoted_fragments == ["numbers keep swimming"]
    assert r.rating == 2
    ElicitationDocument.model_validate_json(doc.model_dump_json())


def test_build_document_rejects_synthetic_id_and_empty_drafts():
    with pytest.raises(ValueError, match="synthetic"):
        build_document(draft("SYN-009"), {"V001": vignette()}, "DOC-0001", NOW)
    unfinished = draft(done=False)
    with pytest.raises(ValueError, match="nothing answered"):
        build_document(unfinished, {"V001": vignette()}, "DOC-0001", NOW)


def test_build_document_gate_needs_answers():
    d = draft()
    d["answers"]["V001"]["answers"]["Q2"] = "  "  # blank gate answer, but Q6 rated
    with pytest.raises(ValueError, match="gate_not_passed"):
        build_document(d, {"V001": vignette()}, "DOC-0001", NOW)


Q4_IDS = ("Q1", "Q2", "Q4", "Q6")


@pytest.mark.parametrize(
    ("raw", "why", "expected", "kept_why"),
    [
        ({"hypothesis": " sleep ", "shift": 2, "toward": "other", "other_explanation": "grief"},
         "Exam stress fits.", {"hypothesis": "sleep", "shift": 2, "toward": "other",
                               "other_explanation": "grief"}, True),
        ({"hypothesis": "", "shift": 0, "toward": "more_adhd"}, "dropped at 0",
         {"hypothesis": None, "shift": 0, "toward": None, "other_explanation": None}, False),
        ({"shift": -1, "toward": "less_adhd", "other_explanation": "x"}, "",
         {"hypothesis": None, "shift": -1, "toward": None, "other_explanation": None}, False),
        ({"shift": 1, "toward": "other", "other_explanation": " "}, "why",
         {"hypothesis": None, "shift": 1, "toward": None, "other_explanation": None}, True),
    ],
)  # fmt: skip
def test_build_document_q4(raw, why, expected, kept_why):
    d = draft(q4=raw)
    d["answers"]["V001"]["answers"]["Q4"] = why
    doc = build_document(d, {"V001": vignette(question_ids=Q4_IDS)}, "DOC-0001", NOW)
    (r,) = doc.responses
    assert r.q4 is not None
    assert r.q4.model_dump() == expected
    assert ("Q4" in r.answers) == kept_why


def test_q4_without_a_shift_is_unanswered():
    import answer_vignettes as av

    assert av.clean_q4({"hypothesis": "typed first"}) is None  # notebook: scale not picked yet
    assert av.q4_summary({"hypothesis": "typed first"}) == "not answered"
    assert av.q4_summary({"shift": 1, "toward": "less_adhd"}) == (
        "+1 partly changes, towards less ADHD-like"
    )
    v, entry = vignette(question_ids=Q4_IDS), draft()["answers"]["V001"]
    assert av.gate_ids(v) == ["Q1", "Q2"] and av.gate_open(v, entry)
    entry["answers"]["Q2"] = " "
    assert not av.gate_open(v, entry) and not av.gate_locked(entry)
    av.pass_gate(entry)
    assert av.gate_locked(entry)


def test_build_document_insufficient_information():
    d = draft(rating=None, insufficient=True)
    doc = build_document(d, {"V001": vignette()}, "DOC-0001", NOW)
    assert doc.responses[0].insufficient_information is True


def test_next_session_id(tmp_path):
    assert next_session_id(tmp_path) == "DOC-0001"
    (tmp_path / "DOC-0001.json").write_text("{}")
    (tmp_path / "DOC-0004.json").write_text("{}")
    (tmp_path / "DOC-SYN-0009.json").write_text("{}")  # synthetic ids are not counted
    assert next_session_id(tmp_path) == "DOC-0005"


# --- claims ------------------------------------------------------------------------------------


def response() -> Response:
    return build_document(draft(), {"V001": vignette()}, "DOC-0001", NOW).responses[0]


def claim(**kw) -> dict:
    return {
        "question_id": "Q1", "claim": "Blurred vision is not an attention sign.",
        "quoted_span_text": "numbers keep swimming", "trait": None, "condition": "unless it recurs",
        "direction": "lowers", **kw,
    }  # fmt: skip


def test_check_claims_accepts_a_valid_reply():
    (c,) = check_claims(json.dumps({"claims": [claim()]}), vignette(), response())
    assert c.vignette_id == "V001" and c.direction == "lowers" and c.question_id == "Q1"


@pytest.mark.parametrize(
    "bad",
    [
        claim(quoted_span_text="numbers keep swimming a lot"),  # not an exact piece
        claim(question_id="Q3"),  # not asked, so not answered
        claim(direction="maybe"),
        claim(claim=""),
    ],
)
def test_check_claims_rejects_broken_claims(bad):
    with pytest.raises(Rejected):
        check_claims(json.dumps({"claims": [bad]}), vignette(), response())


def test_check_claims_rejects_empty_and_non_json():
    with pytest.raises(Rejected):
        check_claims(json.dumps({"claims": []}), vignette(), response())
    with pytest.raises(Rejected):
        check_claims("not json", vignette(), response())


def test_answers_block_has_questions_answers_and_rating():
    block = answers_block(vignette(), response())
    assert block.startswith("Q1:") and "Answer: The" in block and block.endswith("2 of 5")
    assert "Q2:" in block and "Q3" not in block


def test_answers_block_q4():
    d = draft(q4={"hypothesis": "tired eyes", "shift": 1, "toward": "less_adhd"})
    d["answers"]["V001"]["answers"]["Q4"] = "An exam explains the rush."
    v = vignette(question_ids=Q4_IDS)
    r = build_document(d, {"V001": v}, "DOC-0001", NOW).responses[0]
    block = answers_block(v, r)
    assert f"how would it change if {WHATIF}?" in block
    assert (
        "Hypothesis so far: tired eyes\n"
        "Answer: my hypothesis partly changes, towards less ADHD-like (+1)\n"
        "Why: An exam explains the rush."
    ) in block


# --- human ratings -----------------------------------------------------------------------------


def test_parse_scores():
    s = parse_scores("4 5 4 3 5")
    assert s == {
        "key_points": 4, "fidelity": 5, "attribution": 4, "usefulness": 3, "citation_quality": 5,
    }  # fmt: skip
    assert parse_scores("3 - 4 4 -")["fidelity"] is None
    for bad in ("4 5 4 3", "4 5 4 3 9", "- 5 4 3 5", "4 5 - 3 5"):
        with pytest.raises(ValueError):
            parse_scores(bad)


def test_parse_numbers():
    assert parse_numbers("3, 1 3", 4) == [1, 3]
    assert parse_numbers("", 4) == []
    with pytest.raises(ValueError):
        parse_numbers("5", 4)


def test_human_pass_follows_the_rubric_rule():
    ok = parse_scores("3 4 4 4 4")
    assert human_pass(ok, unsupported=False)
    assert not human_pass(ok, unsupported=True)
    assert not human_pass({**ok, "key_points": 2}, False)
    assert not human_pass({**ok, "fidelity": 3}, False)
    assert not human_pass({**ok, "attribution": 3}, False)
    assert human_pass({**ok, "fidelity": None}, False)  # no notes: fidelity does not count


def test_judgment_row_loads_like_a_judge_pass(tmp_path):
    row = judgment_row("Q001", "m", "units", parse_scores("4 4 4 4 4"), False, None, "fine")
    assert row["pass"] is True
    assert parse_sample_judgment(row, expert=True)["pass"] is True  # a valid judge row
    (tmp_path / "judgments_human.json").write_text(json.dumps({"judgments": [row]}))
    assert load_judgments(tmp_path) == {"human": [row]}


# --- chat helpers ------------------------------------------------------------------------------


def test_siblings_include_the_ab_partner():
    a = vignette("V001", VariantInfo(pair_id="P1", arm="A"))
    b = vignette("V002", VariantInfo(pair_id="P1", arm="B", change="the sleep"))
    c = vignette("V003")
    vs = {v.id: v for v in (a, b, c)}
    assert siblings(vs, "V001") == {"V001", "V002"}
    assert siblings(vs, "V003") == {"V003"}


def test_judged_question_carries_the_context_a_judge_needs():
    assert judged_question("a", None, [], "What else?") == "What else?"
    q = judged_question("b", "my text", ["first"], "And now?")
    assert 'Patient text:\n"my text"' in q and "first" in q and q.endswith("Question: And now?")


# --- sessions shared by the terminal app and the notebook --------------------------------------


def test_open_session_and_finish_draft(tmp_path, monkeypatch):
    import answer_vignettes as av

    silver = tmp_path / "synthetic" / "silver" / "vignettes"
    silver.mkdir(parents=True)
    (silver / "V001.json").write_text(vignette().model_dump_json())
    monkeypatch.setattr(av, "FIXTURES", tmp_path)

    with pytest.raises(av.SetupError, match="SYN-"):
        av.open_session("SYN-001", "r", "silver", None)
    with pytest.raises(av.SetupError, match="role"):
        av.open_session("E05", None, "silver", None)
    with pytest.raises(av.SetupError, match="no such vignettes"):
        av.open_session("E05", "r", "silver", ["V404"])

    gold, vignettes, new = av.open_session("E05", "tester, 3 years", "silver", None, "fixed")
    assert gold == tmp_path / "synthetic" / "gold"
    assert new["order"] == ["V001"] and (gold / "vignettes" / "V001.json").exists()
    assert json.loads((gold / "experts.json").read_text()) == {"E05": "tester, 3 years"}

    new["answers"] = draft("E05")["answers"]
    av.write_json(av.draft_path_for(gold, "E05"), new)
    assert av.open_session("E05", None, "silver", None)[2] == new  # resumes the draft

    doc = av.finish_draft(gold, new, vignettes, "silver")
    assert doc.session_id == "DOC-0001" and (gold / "documents" / "DOC-0001.json").exists()
    assert not av.draft_path_for(gold, "E05").exists()
    entries = json.loads((gold / "manifest.json").read_text())["entries"]
    assert {e["kind"] for e in entries} == {"vignette", "document"}

    with pytest.raises(av.SetupError, match="already answered"):
        av.open_session("E05", None, "silver", None)  # nothing left for this expert


def test_migration_leaves_new_q4_answers_alone():
    from migrate_q4_whatif import migrate_document, migrate_draft

    d = draft(q4={"hypothesis": None, "shift": 1, "toward": None})
    d["answers"]["V001"]["answers"]["Q4"] = "An exam explains it."
    v = vignette(question_ids=Q4_IDS)
    doc = build_document(d, {"V001": v}, "DOC-0001", NOW).model_dump(mode="json")
    assert migrate_document(doc) == doc  # 1.1: untouched
    assert migrate_draft(d) == d  # has a scale answer: the why stays
    old = draft()
    old["answers"]["V001"]["answers"]["Q4"] = "answer to the old fragment question"
    assert "Q4" not in migrate_draft(old)["answers"]["V001"]["answers"]


@pytest.mark.parametrize(
    ("q4", "why", "missing"),
    [
        ({"shift": 0}, "", "hypothesis"),
        ({"hypothesis": "tired"}, "", "scale"),
        ({"hypothesis": "tired", "shift": 0}, "", None),  # at 0 nothing more is asked
        ({"hypothesis": "tired", "shift": -1}, "", "why"),
        ({"hypothesis": "tired", "shift": -1}, "sleep explains it", None),
        ({"hypothesis": "tired", "shift": 2}, "because", "which way"),
        ({"hypothesis": "tired", "shift": 2, "toward": "other"}, "because", "other explanation"),
        ({"hypothesis": "tired", "shift": 2, "toward": "other", "other_explanation": "grief"},
         "because", None),
    ],
)  # fmt: skip
def test_q4_parts_are_required_in_the_apps(q4, why, missing):
    import answer_vignettes as av

    got = av.q4_incomplete({"q4": q4, "answers": {"Q4": why}})
    assert (got is None) if missing is None else (missing in (got or "").lower())
