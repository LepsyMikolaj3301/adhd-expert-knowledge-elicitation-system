"""Versioned prompt files (app/prompts.py; scripts/elicitation/prompt_loader.py re-exports it)."""

from pathlib import Path

import pytest

from app.prompts import PROMPTS_DIR, PromptError, _parse_front_matter, load_prompt


def write(tmp_path: Path, name: str, text: str) -> Path:
    (tmp_path / f"{name}.md").write_text(text)
    return tmp_path


CHAT = """---
id: Demo
version: 3
endpoint: Ollama /api/chat: "raw": true
options: {seed: 7, tags: [a, b]}
broken: {not yaml
---
preamble that is ignored
# System
You are {{ROLE}}.
# User
Question: {{QUESTION}}   (e.g. what time is it)
{{IF_VARIANT}}Only for variants: {{VARIANT_NOTE}}{{END_IF}}
"""


# --- the files in the repository ---------------------------------------------------------------


def test_every_prompt_of_the_repository_loads():
    paths = list(PROMPTS_DIR.glob("*.v*.md"))
    assert paths
    for path in paths:
        prompt = load_prompt(path.stem)
        assert prompt.id and prompt.version >= 1 and prompt.user


def test_filling_a_real_prompt_is_strict():
    prompt = load_prompt("Synthetic_expert_answer.v1")
    full = dict(
        PERSONA="x", FIXTURE_KIND="clean", FRAMING="email", VIGNETTE_TEXT="t", QUESTIONS="q"
    )
    filled = prompt.fill(**full)
    assert "{{" not in filled.user and "(e.g." not in filled.user
    with pytest.raises(PromptError, match="missing"):
        prompt.fill(PERSONA="x")
    with pytest.raises(PromptError, match="unused"):
        prompt.fill(**full, EXTRA="1")


# --- front matter ------------------------------------------------------------------------------


def test_front_matter_is_split_at_the_first_colon_and_flow_values_are_yaml():
    meta = _parse_front_matter(
        'id: Demo\nendpoint: Ollama /api/chat: "raw": true\noptions: {seed: 7}\nlist: [1, 2]\n'
    )
    assert meta == {
        "id": "Demo",
        "endpoint": 'Ollama /api/chat: "raw": true',
        "options": {"seed": 7},
        "list": [1, 2],
    }


def test_a_flow_value_that_is_not_yaml_stays_a_string():
    assert _parse_front_matter("x: {not yaml")["x"] == "{not yaml"


def test_a_front_matter_line_without_a_colon_is_refused():
    with pytest.raises(PromptError, match="bad front-matter line"):
        _parse_front_matter("id: Demo\njust words\n")


# --- loading -----------------------------------------------------------------------------------


def test_a_chat_prompt_has_its_system_and_user_sections(tmp_path):
    prompt = load_prompt("chat", write(tmp_path, "chat", CHAT))
    assert (prompt.id, prompt.version) == ("Demo", 3)
    assert prompt.meta["options"] == {"seed": 7, "tags": ["a", "b"]}
    assert prompt.system == "You are {{ROLE}}."
    assert prompt.user.startswith("Question: {{QUESTION}}")


def test_a_template_prompt_has_no_system_message(tmp_path):
    folder = write(
        tmp_path, "raw", "---\nid: Raw\nversion: 1\n---\n# Template\nContinue: {{TEXT}}\n"
    )
    prompt = load_prompt("raw", folder)
    assert prompt.system is None and prompt.user == "Continue: {{TEXT}}"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("id: x\nversion: 1\n# User\nhi", "no front-matter"),
        ("---\nid: x\nversion: 1\n---\nonly a preamble", "needs a '# User' or '# Template'"),
        (
            "---\nid: x\nversion: 1\n---\n# System\nonly a system",
            "needs a '# User' or '# Template'",
        ),
    ],
)
def test_a_malformed_prompt_file_says_what_is_missing(tmp_path, text, message):
    with pytest.raises(PromptError, match=message):
        load_prompt("bad", write(tmp_path, "bad", text))


# --- filling -----------------------------------------------------------------------------------


@pytest.fixture
def chat(tmp_path):
    return load_prompt("chat", write(tmp_path, "chat", CHAT))


def test_variables_fill_both_messages_and_the_example_hint_is_dropped(chat):
    filled = chat.fill(ROLE="a clinician", QUESTION=42)
    assert filled.system == "You are a clinician."
    assert filled.user == "Question: 42"  # an int is fine; the hint and the IF block are gone


def test_the_variant_block_is_kept_only_when_asked_for(chat):
    kept = chat.fill(ROLE="r", QUESTION="q", IF_VARIANT=True, VARIANT_NOTE="note")
    assert kept.user.endswith("Only for variants: note")
    assert "Only for variants" not in chat.fill(ROLE="r", QUESTION="q", IF_VARIANT=False).user


def test_a_missing_or_unused_variable_is_an_error(chat):
    with pytest.raises(PromptError, match=r"missing variables \['QUESTION'\]"):
        chat.fill(ROLE="r")
    with pytest.raises(PromptError, match=r"unused variables \['EXTRA'\]"):
        chat.fill(ROLE="r", QUESTION="q", EXTRA="x")


def test_filling_does_not_change_the_template(chat):
    chat.fill(ROLE="r", QUESTION="q")
    assert chat.system == "You are {{ROLE}}."
