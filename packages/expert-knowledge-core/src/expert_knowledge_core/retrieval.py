"""Retrieval constants the evaluations settled on (notes/new-chips-knowledge.md,
notes/chips-test-findings.md)."""

RRF_K = 60  # reciprocal rank fusion: score = sum over rankings of 1 / (RRF_K + rank)
FUSION_DEPTH = 50  # candidates taken from each ranking before fusing
NEAR_DUPLICATE = 0.9  # cosine of two case units that count as the same generic answer
PATIENT_TOP_CUES = 10  # cue keys kept per patient sentence
CONTEXT_BONUS = 0.5  # weight of a matching co-cited highlight
EMBEDDING_DIMENSIONS = 1024  # bge-m3, the model the stored vectors were made with
EMBEDDING_MODEL = "bge-m3"
