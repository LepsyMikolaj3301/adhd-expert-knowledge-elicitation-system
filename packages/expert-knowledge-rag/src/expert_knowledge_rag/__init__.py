"""LangChain access to the expert knowledge database.

    store = ExpertKnowledgeStore("postgresql://...")            # read-only, schema `chips`
    retriever = ExpertQuestionRetriever(store=store, embeddings=default_embeddings(), k=4)
    notes = retriever.invoke("How do I tell sleep deprivation from attention problems?")

See the README for the patient-text retriever, the answer chains and the filters.
"""

from expert_knowledge_rag.chains import expert_answer_chain, patient_answer_chain
from expert_knowledge_rag.filters import ExpertFilter
from expert_knowledge_rag.ollama import default_embeddings
from expert_knowledge_rag.prompts import expert_prompt, format_notes, patient_prompt
from expert_knowledge_rag.retrievers import ExpertQuestionRetriever, PatientTextRetriever
from expert_knowledge_rag.store import ExpertKnowledgeStore

__all__ = [
    "ExpertFilter",
    "ExpertKnowledgeStore",
    "ExpertQuestionRetriever",
    "PatientTextRetriever",
    "default_embeddings",
    "expert_answer_chain",
    "expert_prompt",
    "format_notes",
    "patient_answer_chain",
    "patient_prompt",
]
