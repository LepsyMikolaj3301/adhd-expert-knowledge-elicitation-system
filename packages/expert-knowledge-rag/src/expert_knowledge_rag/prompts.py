"""The evaluated prompts as LangChain prompt templates."""

from collections.abc import Sequence

from langchain_core.documents import Document
from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from expert_knowledge_core import prompts as core


def format_notes(docs: Sequence[Document]) -> str:
    """`[E1] note` blocks, the form the generator was evaluated with."""
    return core.format_notes([d.page_content for d in docs])


def expert_prompt() -> ChatPromptTemplate:
    """Variables: `notes` (see format_notes) and `question`."""
    return ChatPromptTemplate.from_messages(
        [
            SystemMessage(content=core.EXPERT_SYSTEM_PROMPT),
            ("human", "Notes:\n\n{notes}\n\nQuestion: {question}"),
        ]
    )


def patient_prompt() -> ChatPromptTemplate:
    """Variables: `notes`, `patient_text` and `question`."""
    return ChatPromptTemplate.from_messages(
        [
            SystemMessage(content=core.PATIENT_SYSTEM_PROMPT),
            (
                "human",
                'Notes:\n\n{notes}\n\nPatient text:\n"{patient_text}"\n\nQuestion: {question}',
            ),
        ]
    )
