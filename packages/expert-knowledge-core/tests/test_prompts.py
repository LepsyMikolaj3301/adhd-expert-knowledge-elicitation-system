from expert_knowledge_core.prompts import (
    EXPERT_SYSTEM_PROMPT,
    NOT_IN_SOURCES,
    PATIENT_SYSTEM_PROMPT,
    build_expert_prompt,
    build_patient_prompt,
    format_notes,
)


def test_notes_are_numbered_from_one():
    assert format_notes(["a", "b"]) == "[E1] a\n\n[E2] b"


def test_expert_prompt_formats():
    assert build_expert_prompt("Why?", []) == "Question: Why?"
    assert build_expert_prompt("Why?", ["a"]) == "Notes:\n\n[E1] a\n\nQuestion: Why?"


def test_patient_prompt_formats():
    assert build_patient_prompt("I sleep badly.", "What?", ["a"]) == (
        'Notes:\n\n[E1] a\n\nPatient text:\n"I sleep badly."\n\nQuestion: What?'
    )
    assert "(none)" in build_patient_prompt("x", "y", [])


def test_system_prompts_name_the_abstention_reply():
    assert f"reply exactly: {NOT_IN_SOURCES}" in EXPERT_SYSTEM_PROMPT
    assert f"reply exactly: {NOT_IN_SOURCES}" in PATIENT_SYSTEM_PROMPT
