"""Reading vignette files and what-ifs, and the content rules, without a database."""

import json
from pathlib import Path

import pytest

from app.core.errors import DomainError
from app.vignettes.importing import plan_import, read_whatifs
from app.vignettes.schemas import VersionContent
from app.vignettes.service import opening_words, validate_content

TEXT = "I reorganised my entire desk instead of starting the report. I slept badly all week."
CUE = "reorganised my entire desk"


def vignette_file(folder: Path, code: str = "V001", **fields) -> Path:
    raw = {
        "id": code,
        "text": TEXT,
        "framing": "personal_journal",
        "design": {"planted_cues": [{"quote": CUE, "trait": "avoidance", "strength": "weak"}]},
        **fields,
    }
    path = folder / f"{code}.json"
    path.write_text(json.dumps(raw))
    return path


def code_of(fn, *args) -> str:
    with pytest.raises(DomainError) as error:
        fn(*args)
    return error.value.code


# --- what-if files -----------------------------------------------------------------------------


def test_a_what_if_file_maps_codes_to_text(tmp_path):
    path = tmp_path / "w.json"
    path.write_text('{"V001": "the writer had an exam"}')
    assert read_whatifs(path) == {"V001": "the writer had an exam"}


@pytest.mark.parametrize("content", ["not json", "[1, 2]", '{"V001": 5}', '{"V001": null}', ""])
def test_an_unreadable_what_if_file_is_refused(tmp_path, content):
    path = tmp_path / "w.json"
    path.write_text(content)
    assert code_of(read_whatifs, path) == "whatifs_unreadable"


def test_a_missing_what_if_file_is_refused(tmp_path):
    assert code_of(read_whatifs, tmp_path / "absent.json") == "whatifs_unreadable"


# --- planning an import ------------------------------------------------------------------------


def test_every_file_with_a_what_if_becomes_a_draft_content(tmp_path):
    vignette_file(tmp_path, "V001")
    vignette_file(tmp_path, "V002")
    contents = plan_import(tmp_path, {"V001": "an exam", "V002": " a move "})
    assert sorted(contents) == ["V001", "V002"]
    assert contents["V002"].q4_whatif == "a move"  # trimmed
    assert contents["V001"].design.planted_cues[0].quote == CUE


@pytest.mark.parametrize("directory", ["empty", "absent"])
def test_a_folder_without_vignettes_is_refused(tmp_path, directory):
    (tmp_path / "empty").mkdir()
    assert code_of(plan_import, tmp_path / directory, {}) == "no_vignette_files"


def test_every_problem_is_named_and_nothing_is_planned(tmp_path):
    vignette_file(tmp_path, "V001")  # no what-if
    vignette_file(tmp_path, "V002", framing="telegram")  # invalid framing
    vignette_file(
        tmp_path,
        "V003",
        design={"planted_cues": [{"quote": "absent words", "trait": "t", "strength": "weak"}]},
    )
    (tmp_path / "V004.json").write_text("{broken")
    with pytest.raises(DomainError) as error:
        plan_import(tmp_path, {"V002": "x", "V003": "y", "V004": "z", "V009": "no file"})
    assert error.value.code == "import_refused"
    message = error.value.message
    assert "V001.json: no what-if for this vignette." in message
    assert "V002.json" in message and "V003.json" in message and "V004.json" in message
    assert "V009: a what-if but no vignette file." in message


def test_a_blank_what_if_counts_as_missing(tmp_path):
    vignette_file(tmp_path, "V001")
    with pytest.raises(DomainError, match="no what-if"):
        plan_import(tmp_path, {"V001": "   "})


# --- the rules that span fields ----------------------------------------------------------------


def content(**fields) -> VersionContent:
    base = {
        "text": TEXT,
        "framing": "email",
        "q4_whatif": "an exam",
        "design": {"planted_cues": [{"quote": CUE, "trait": "t", "strength": "weak"}]},
    }
    return VersionContent.model_validate({**base, **fields})


def test_valid_content_passes():
    validate_content(content())


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"q4_whatif": None}, "q4_without_whatif"),
        ({"q4_whatif": "  "}, "q4_without_whatif"),
        (
            {
                "design": {
                    "is_control": True,
                    "planted_cues": [{"quote": CUE, "trait": "t", "strength": "weak"}],
                }
            },
            "control_with_cues",
        ),
        ({"design": {"track": "text_analysis"}}, "track_without_target"),
        ({"variant": {"pair_id": "P1", "arm": "B"}}, "variant_b_without_change"),
        (
            {
                "design": {
                    "confounders": [{"quote": "not in the text", "alternative_explanation": "x"}]
                }
            },
            "span_not_in_text",
        ),
        (
            {"design": {"planted_cues": [{"quote": "nowhere", "trait": "t", "strength": "weak"}]}},
            "span_not_in_text",
        ),
    ],
)
def test_content_rules_have_stable_codes(fields, code):
    assert code_of(validate_content, content(**fields)) == code


def test_a_control_without_cues_and_arm_a_without_a_change_are_fine():
    validate_content(content(design={"is_control": True}, variant={"pair_id": "P", "arm": "A"}))
    validate_content(content(design={"track": "text_analysis", "knowledge_target": "pragmatics"}))


@pytest.mark.parametrize(
    ("text", "count", "preview"),
    [
        ("one two three", 40, "one two three"),
        ("a b c d", 2, "a b…"),
        ("", 3, ""),
        (" a  b ", 5, "a b"),
    ],
)
def test_a_preview_is_the_first_words(text, count, preview):
    assert opening_words(text, count) == preview
