from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.retrievers import BaseRetriever

from expert_knowledge_core import prompts as core
from expert_knowledge_rag import (
    expert_answer_chain,
    expert_prompt,
    format_notes,
    patient_answer_chain,
    patient_prompt,
)


class FixedRetriever(BaseRetriever):
    docs: list[Document]
    seen: list[str] = []

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        self.seen.append(query)
        return self.docs


class ExplodingModel(FakeListChatModel):
    def _generate(self, *args: Any, **kwargs: Any):
        raise AssertionError("the model must not be called without notes")


DOCS = [Document(page_content="first note"), Document(page_content="second note")]


def human(prompt, **values) -> str:
    return prompt.format_messages(**values)[1].content


def test_templates_give_exactly_the_evaluated_messages():
    notes = format_notes(DOCS)
    assert notes == "[E1] first note\n\n[E2] second note"
    assert human(expert_prompt(), notes=notes, question="Why?") == core.build_expert_prompt(
        "Why?", ["first note", "second note"]
    )
    assert human(
        patient_prompt(), notes=notes, patient_text="I sleep badly.", question="What?"
    ) == core.build_patient_prompt("I sleep badly.", "What?", ["first note", "second note"])
    assert (
        expert_prompt().format_messages(notes=notes, question="Why?")[0].content
        == core.EXPERT_SYSTEM_PROMPT
    )


def test_braces_in_notes_or_questions_are_not_template_variables():
    out = human(expert_prompt(), notes="[E1] {not a variable}", question="a {b}?")
    assert "{not a variable}" in out and "a {b}?" in out


def test_expert_chain_answers_from_the_notes():
    retriever = FixedRetriever(docs=DOCS)
    result = expert_answer_chain(
        retriever, FakeListChatModel(responses=["They read it as X [E1]."])
    ).invoke("Why?")
    assert result["answer"] == "They read it as X [E1]."
    assert result["notes"] == DOCS and retriever.seen == ["Why?"]


def test_expert_chain_accepts_a_dict():
    chain = expert_answer_chain(FixedRetriever(docs=DOCS), FakeListChatModel(responses=["ok"]))
    assert chain.invoke({"question": "Why?"})["answer"] == "ok"


def test_without_notes_the_model_is_not_called():
    chain = expert_answer_chain(FixedRetriever(docs=[]), ExplodingModel(responses=["x"]))
    assert chain.invoke("Why?") == {"answer": core.NOT_IN_SOURCES, "notes": []}


def test_patient_chain_retrieves_with_the_text_and_defaults_the_question():
    retriever = FixedRetriever(docs=DOCS, seen=[])
    model = FakeListChatModel(responses=["Reads as X [E2]."])
    result = patient_answer_chain(retriever, model).invoke("I sleep badly.")
    assert result["answer"] == "Reads as X [E2]." and retriever.seen == ["I sleep badly."]


async def test_chains_run_async():
    chain = expert_answer_chain(
        FixedRetriever(docs=DOCS), FakeListChatModel(responses=["async ok"])
    )
    assert (await chain.ainvoke("Why?"))["answer"] == "async ok"
