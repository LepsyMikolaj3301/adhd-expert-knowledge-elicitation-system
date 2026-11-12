"""Step 3 of the chip pipeline inside the backend: a local model files sentences, ids only."""

import json

import chip_findings
import pytest

from app.knowledge import classifier, findings
from app.prompts import PROMPTS_DIR, load_prompt

TEXT = "I haven't slept well since moving. The report falls apart again like last week."


def setup_case():
    resp = findings.Response(
        vignette_id="V001",
        vignette_version=1,
        answers={
            "Q1": "⟦h1⟧ explains it. Hard to say more than that.",
            "Q3": "What was it like before?",
        },
        highlights=[findings.Highlight(1, "I haven't slept well since moving", (0, 33), "away")],
        rating=None,
        insufficient_information=False,
    )
    highlights, sentences = chip_findings.assign(resp, TEXT)
    return highlights, sentences, findings.unresolved(sentences)


def test_the_prompt_file_is_found_from_the_backend():
    assert (PROMPTS_DIR / "Expert_sentence_targets.v1.md").exists()
    assert load_prompt("Expert_sentence_targets.v1").user


def test_the_prompt_lists_highlights_and_the_sentences_to_file():
    highlights, sentences, left = setup_case()
    prompt = classifier.prompt_for(TEXT, highlights, sentences, left)
    assert "h1" in prompt.user and "I haven't slept well" in prompt.user
    assert "Q3.1" in prompt.user


def test_valid_labels_are_accepted():
    highlights, sentences, left = setup_case()
    allowed = {h["id"] for h in highlights} | {"case", "prev"}
    raw = json.dumps({"Q3.1": ["case"]})
    assert classifier.check_labels(raw, sentences, left, allowed) == ({"Q3.1": ["case"]}, [])


@pytest.mark.parametrize(
    "raw, fragment",
    [
        ("not json at all", "JSON"),
        ('{"Q3.1": ["h9"]}', "unknown ids"),
        ('{"Q3.1": ["prev"]}', "prev"),  # first sentence of its answer
        ("{}", "missing"),
        ('["case"]', "JSON"),
    ],
)
def test_bad_replies_are_reported_not_raised(raw, fragment):
    highlights, sentences, left = setup_case()
    allowed = {h["id"] for h in highlights} | {"case", "prev"}
    good, errors = classifier.check_labels(raw, sentences, left, allowed)
    assert good == {} and any(fragment in e for e in errors)


async def test_nothing_to_file_means_no_call(monkeypatch):
    async def ask(system, user, seed):
        raise AssertionError("the model was called")

    monkeypatch.setattr(classifier, "ask", ask)
    labels, info = await classifier.classify(TEXT, [], [], [])
    assert labels == {} and info["attempts"] == 0


async def test_an_invalid_reply_is_asked_again_with_a_new_seed(monkeypatch):
    highlights, sentences, left = setup_case()
    seeds = []

    async def ask(system, user, seed):
        seeds.append(seed)
        return "garbage" if len(seeds) == 1 else json.dumps({"Q3.1": ["case"]})

    monkeypatch.setattr(classifier, "ask", ask)
    labels, info = await classifier.classify(TEXT, highlights, sentences, left)
    assert labels == {"Q3.1": ["case"]}
    assert info["attempts"] == 2 and len(set(seeds)) == 2 and info["errors"] == []


async def test_a_model_that_keeps_failing_leaves_the_sentence_to_the_case_fallback(monkeypatch):
    highlights, sentences, left = setup_case()
    calls = 0

    async def ask(system, user, seed):
        nonlocal calls
        calls += 1
        return "garbage"

    monkeypatch.setattr(classifier, "ask", ask)
    labels, info = await classifier.classify(TEXT, highlights, sentences, left, retries=2)
    assert labels == {} and calls == 3 and info["errors"]
    assert findings.apply_classification(sentences, labels) == ["Q3.1"]


async def test_an_unreachable_model_is_an_error_not_a_quiet_fallback(monkeypatch):
    highlights, sentences, left = setup_case()

    async def ask(system, user, seed):
        raise ConnectionError("ollama is down")

    monkeypatch.setattr(classifier, "ask", ask)
    with pytest.raises(ConnectionError):
        await classifier.classify(TEXT, highlights, sentences, left)
