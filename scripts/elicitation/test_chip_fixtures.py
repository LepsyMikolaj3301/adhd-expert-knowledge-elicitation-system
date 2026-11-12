"""Tests for the reply checks of make_chip_fixtures.py (run by path, see test_chip_findings.py)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import make_chip_fixtures as mk  # noqa: E402
from elicitation_schema import Vignette, VignetteDesign, content_hash  # noqa: E402
from make_fixtures import Rejected  # noqa: E402

TEXT = (
    "I only opened the file at nine because I did the dishes first. The report is due on Friday "
    "and I told myself two hours. The street is louder than the old one, so I woke at five."
)


def vignette(variant=None) -> Vignette:
    return Vignette(
        id="V001", version=1, text=TEXT, content_hash=content_hash(TEXT),
        framing="personal_journal", variant=variant,
        question_ids=["Q1", "Q2", "Q3", "Q5", "Q6"], design=VignetteDesign(purpose="test"),
    )  # fmt: skip


def reply(**patch) -> dict:
    base = {
        "highlights": [
            {"chip": 1, "text": "I only opened the file at nine", "direction": "toward"},
            {"chip": 2, "text": "I woke at five", "direction": "away"},
        ],
        "answers": {
            "Q1": "⟦h1⟧ is a late start.",
            "Q2": "⟦h2⟧ could be sleep.",
            "Q3": "A calmer week.",
            "Q5": "Over-reading ⟦h1⟧.",
        },
        "overall_rating": 2,
        "insufficient_information": False,
        "gold_claims": [
            {"question_id": "Q1", "claim": "A late start is weak evidence.",
             "quoted_span_text": "I only opened the file at nine", "trait": "task_initiation",
             "condition": None, "direction": "raises"}
        ],
    }  # fmt: skip
    return base | patch


def check(data, kind="clean", v=None):
    return mk.chip_answer_pieces(data, v or vignette(), kind, mk.forbidden_for(v or vignette()))


def test_a_good_reply_passes():
    answers, highlights, rating, insufficient, claims = check(reply())
    assert [h.chip for h in highlights] == [1, 2] and highlights[1].span[0] == TEXT.index("I woke")
    assert (
        rating == 2
        and not insufficient
        and len(claims) == 1
        and set(answers) == set(mk.OPEN_QUESTIONS)
    )


@pytest.mark.parametrize(
    "patch, why",
    [
        (
            {
                "highlights": [{"chip": 1, "text": "not in the text at all", "direction": "away"}]
                * 2
            },
            "substring",
        ),
        (
            {"highlights": [{"chip": 2, "text": "I woke at five", "direction": "away"}] * 2},
            "in order",
        ),
        ({"answers": {"Q1": "⟦h4⟧ x.", "Q2": "b", "Q3": "c", "Q5": "d"}}, "not highlights"),
        ({"answers": {"Q1": "a", "Q2": "b", "Q3": "c", "Q5": "d"}}, "no chip"),
        (
            {"answers": {"Q1": "⟦h1⟧ as the persona would.", "Q2": "b", "Q3": "c", "Q5": "d"}},
            "persona",
        ),
        ({"overall_rating": None}, "overall_rating"),
        ({"gold_claims": []}, "no reference claims"),
    ],
)
def test_bad_replies_are_rejected(patch, why):
    with pytest.raises(Rejected, match=why):
        check(reply(**patch))


def test_personality_is_not_persona_talk():
    answers = reply()["answers"] | {"Q2": "⟦h2⟧ or a talkative personality."}
    check(reply(answers=answers))


def test_insufficient_info_may_cite_no_chip_and_has_no_rating():
    answers = {"Q1": "Cannot say.", "Q2": "b", "Q3": "c", "Q5": "d"}
    out = check(
        reply(answers=answers, insufficient_information=True, gold_claims=[]), "insufficient_info"
    )
    assert out[2] is None and out[3] is True


def test_variant_b_answers_may_not_mention_the_removed_newborn():
    from elicitation_schema import VariantInfo

    b = vignette(VariantInfo(pair_id="S05", arm="B", change="no newborn"))
    answers = reply()["answers"] | {"Q3": "Is there a baby at home?"}
    with pytest.raises(Rejected, match="removed"):
        check(reply(answers=answers), v=b)
    # generic words stay allowed: the question text itself talks about poor sleep
    check(reply(answers=reply()["answers"] | {"Q3": "Was sleep poor that night?"}), v=b)
