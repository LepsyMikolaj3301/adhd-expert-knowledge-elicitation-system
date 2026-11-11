import numpy as np
import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from expert_knowledge_core.example import example_record

DIMENSIONS = 1024


@pytest.fixture(scope="session")
def embeddings() -> DeterministicFakeEmbedding:
    """Stands in for bge-m3: the same text always gets the same vector."""
    return DeterministicFakeEmbedding(size=DIMENSIONS)


@pytest.fixture
def record():
    return example_record("S1", "X1")


def vector_text(values) -> str:
    return "[" + ",".join(f"{v:.8g}" for v in np.asarray(values)) + "]"
