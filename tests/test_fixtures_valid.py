import json

import pytest
from leak_terms import find_leaks
from prompt_loader import PROMPTS_DIR, PromptError, load_prompt
from pydantic import ValidationError

from app.elicitation.lifecycle import (
    DocumentStatus,
    SyntheticIngestionError,
    assert_ingestible,
    check_transition,
)
from app.elicitation.schema import (
    MAX_WORDS,
    MIN_WORDS,
    ElicitationDocument,
    ReferenceClaim,
    Vignette,
)


def error_codes(e: ValidationError) -> set[str]:
    """Stable codes: our messages start with 'code:'; an unknown question id is a literal error."""
    codes = set()
    for err in e.errors():
        if err["type"] == "literal_error" and any(str(p).startswith("Q") for p in err["loc"]):
            codes.add("unknown_question_id")
        elif err["type"] == "value_error":
            codes.add(str(err["ctx"]["error"]).split(":")[0])
    return codes


# --- generated fixtures ---


def test_documents_validate(documents, tier):
    assert documents
    for name, raw in documents.items():
        doc = ElicitationDocument.model_validate(raw)
        assert doc.session_id == name
        assert doc.is_synthetic == (tier != "gold")  # gold = real experts
        assert doc.expert_id.startswith("SYN-") == doc.is_synthetic
        assert doc.responses


def test_vignettes_follow_generator_rules(vignettes):
    assert vignettes
    for raw in vignettes.values():
        v = Vignette.model_validate(raw)
        assert MIN_WORDS <= v.word_count <= MAX_WORDS
        assert find_leaks(v.text) == []


def test_ab_pairs_are_whole(vignettes):
    arms = {}
    for raw in vignettes.values():
        v = Vignette.model_validate(raw)
        if v.variant:
            arms.setdefault(v.variant.pair_id, set()).add(v.variant.arm)
    assert all(a == {"A", "B"} for a in arms.values())


def test_claims_match_documents(documents, claims):
    assert set(claims) == set(documents)
    for name, claim_list in claims.items():
        doc = ElicitationDocument.model_validate(documents[name])
        texts = {v.id: v.text for v in doc.vignettes}
        answered = {r.vignette_id for r in doc.responses}
        for raw in claim_list:
            claim = ReferenceClaim.model_validate(raw)
            assert claim.vignette_id in answered
            if claim.quoted_span_text is not None:
                assert claim.quoted_span_text in texts[claim.vignette_id]


def test_manifest_lists_every_file(tier_dir, tier):
    manifest = json.loads((tier_dir / "manifest.json").read_text())
    assert manifest["tier"] == tier and manifest["quality"]
    for entry in manifest["entries"]:
        assert (tier_dir / entry["path"]).exists()
        assert entry["tier"] == tier
        assert {"id", "kind", "source", "prompt", "model", "seed", "created_at"} <= entry.keys()


def test_text_analysis_vignettes_exist(vignettes):
    """The knowledge-gap track must be present and say what knowledge it targets."""
    track = [
        Vignette.model_validate(v)
        for v in vignettes.values()
        if v["design"]["track"] == "text_analysis"
    ]
    assert track and all(v.design.knowledge_target for v in track)
    assert any(v.design.is_control for v in track)  # hard negative


# --- hand-written edge cases ---


def test_edge_cases_fail_with_named_error(edge_cases):
    assert len(edge_cases) == 6
    for name, case in edge_cases.items():
        with pytest.raises(ValidationError) as exc:
            ElicitationDocument.model_validate(case["document"])
        assert case["expected_error"] in error_codes(exc.value), name


# --- rules around the document ---


def test_synthetic_guard_blocks_production_ingestion(documents, tier):
    doc = ElicitationDocument.model_validate(next(iter(documents.values())))
    if tier == "gold":
        assert_ingestible(doc, production=True)  # real expert answers may be ingested
        return
    with pytest.raises(SyntheticIngestionError):
        assert_ingestible(doc, production=True)
    assert_ingestible(doc, production=False)


def test_lifecycle_transitions():
    check_transition(DocumentStatus.SUBMITTED, DocumentStatus.EXTRACTED)
    check_transition(DocumentStatus.MEMBER_CHECKED, DocumentStatus.REJECTED)
    with pytest.raises(ValueError):
        check_transition(DocumentStatus.SUBMITTED, DocumentStatus.APPROVED)
    with pytest.raises(ValueError):
        check_transition(DocumentStatus.APPROVED, DocumentStatus.REJECTED)


def test_expert_view_hides_design(vignettes):
    v = Vignette.model_validate(next(iter(vignettes.values())))
    assert "design" not in v.expert_view()


# --- prompt loader ---


def test_all_prompts_load():
    for path in PROMPTS_DIR.glob("*.v*.md"):
        p = load_prompt(path.stem)
        assert p.id and p.version >= 1 and p.user


def test_prompt_fill_is_strict():
    p = load_prompt("Synthetic_expert_answer.v1")
    full = dict(
        PERSONA="x", FIXTURE_KIND="clean", FRAMING="email", VIGNETTE_TEXT="t", QUESTIONS="q"
    )
    filled = p.fill(**full)
    assert "{{" not in filled.user and "(e.g." not in filled.user
    with pytest.raises(PromptError, match="missing"):
        p.fill(PERSONA="x")
    with pytest.raises(PromptError, match="unused"):
        p.fill(**full, EXTRA="1")


def test_leak_terms():
    assert find_leaks("He was Diagnosed with ADHD, took Ritalin") == [
        "diagnosed",
        "adhd",
        "ritalin",
    ]
    assert find_leaks("I paid the address bill") == []
