"""Answer chains: retrieve notes, ask the model to report them, cite them as [E#].

The models and prompts are the evaluated ones (expert-knowledge-core). With no notes the model is
not called: the answer is NOT_IN_SOURCES, because without notes it answers from general knowledge
and passes nothing (notes/expert-knowledge.md).
"""

from operator import itemgetter
from typing import Any

from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.retrievers import BaseRetriever
from langchain_core.runnables import Runnable, RunnableLambda, RunnablePassthrough

from expert_knowledge_core.prompts import NOT_IN_SOURCES
from expert_knowledge_rag.prompts import expert_prompt, format_notes, patient_prompt

DEFAULT_PATIENT_QUESTION = "What do the notes say about how this text should be read?"


def _answer(prompt: Runnable, llm: BaseChatModel) -> Any:
    def route(inputs: dict[str, Any]) -> Runnable:
        docs: list[Document] = inputs["docs"]
        if not docs:
            return RunnableLambda(lambda _: {"answer": NOT_IN_SOURCES, "notes": []})
        return RunnablePassthrough.assign(notes=lambda x: format_notes(x["docs"])) | {
            "answer": prompt | llm | StrOutputParser(),
            "notes": lambda x: x["docs"],
        }

    return RunnableLambda(route)


def expert_answer_chain(retriever: BaseRetriever, llm: BaseChatModel) -> Runnable:
    """`"question"` or `{"question": ...}` -> `{"answer": str, "notes": [Document]}`."""

    def normalise(inputs: str | dict[str, Any]) -> dict[str, Any]:
        return {"question": inputs} if isinstance(inputs, str) else dict(inputs)

    return (
        RunnableLambda(normalise)
        | RunnablePassthrough.assign(docs=itemgetter("question") | retriever)
        | _answer(expert_prompt(), llm)
    )


def patient_answer_chain(retriever: BaseRetriever, llm: BaseChatModel) -> Runnable:
    """`"patient text"` or `{"patient_text": ..., "question": ...}` (question optional) ->
    `{"answer": str, "notes": [Document]}`. Use with a PatientTextRetriever."""

    def normalise(inputs: str | dict[str, Any]) -> dict[str, Any]:
        data = {"patient_text": inputs} if isinstance(inputs, str) else dict(inputs)
        return {"question": DEFAULT_PATIENT_QUESTION, **data}

    return (
        RunnableLambda(normalise)
        | RunnablePassthrough.assign(docs=itemgetter("patient_text") | retriever)
        | _answer(patient_prompt(), llm)
    )
