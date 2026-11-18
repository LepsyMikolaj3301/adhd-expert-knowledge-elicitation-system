"""LangChain's standard retriever tests, against the seeded schema (see conftest.py).

Both seeded sessions are searched: with the second one there are enough notes for the suite's
`k=3`. The patient retriever does not merge units here, for the
same reason (the cue keys are shared, so there are only 8 fragment units in 2 sessions).
"""

import pytest
from langchain_tests.integration_tests import RetrieversIntegrationTests

from expert_knowledge_rag import ExpertQuestionRetriever, PatientTextRetriever

pytestmark = pytest.mark.integration


class _Wired:
    @pytest.fixture(autouse=True)
    def _wire(self, store, embeddings):
        self.store, self.embeddings = store, embeddings


class TestExpertQuestionRetriever(_Wired, RetrieversIntegrationTests):
    @property
    def retriever_constructor(self):
        return ExpertQuestionRetriever

    @property
    def retriever_constructor_params(self):
        return {
            "store": self.store,
            "embeddings": self.embeddings,
        }

    @property
    def retriever_query_example(self):
        return "How do I tell sleep deprivation from attention problems?"


class TestPatientTextRetriever(_Wired, RetrieversIntegrationTests):
    @property
    def retriever_constructor(self):
        return PatientTextRetriever

    @property
    def retriever_constructor_params(self):
        return {
            "store": self.store,
            "embeddings": self.embeddings,
            "merge_shared": False,
        }

    @property
    def retriever_query_example(self):
        return "every time I try to type a formula my hand starts shaking slightly"
