"""BM25 as sparse vectors for pgvector's `sparsevec`.

Each chunk stores its BM25 term weights, `idf(t) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl /
avgdl))`; a query is the count of each of its terms. The inner product of the two is then the
BM25 score, so `sparse <#> query` (negative inner product) ranks by -BM25. Terms are hashed into
`DIMENSIONS` dimensions, so no vocabulary has to be stored (a collision only merges two terms).
"""

import hashlib
import math
import re
from collections import Counter

from pgvector import SparseVector
from pydantic import BaseModel, ConfigDict, Field
from snowballstemmer import stemmer as snowball

DIMENSIONS = 1 << 20  # must match the sparsevec(1048576) columns (chunks.sparse, chips.*)


class Bm25Config(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a typo in the YAML fails on load

    k1: float = Field(1.2, gt=0)
    b: float = Field(0.75, ge=0, le=1)
    stemmer: str | None = "english"  # a Snowball language, or null for no stemming


_STOP_TEXT = (
    "a an and are as at be been but by for from had has have he her his i if in into is it its "
    "of on or she so such than that the their then there these they this to was were which will "
    "with would you your"
)
STOPWORDS = frozenset(_STOP_TEXT.split())
_TOKEN = re.compile(r"[a-z0-9]+")


class Tokenizer:
    def __init__(self, cfg: Bm25Config) -> None:
        self._stem = snowball(cfg.stemmer).stemWord if cfg.stemmer else None

    def __call__(self, text: str) -> list[str]:
        tokens = [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]
        return [self._stem(t) for t in tokens] if self._stem else tokens


def term_dim(token: str) -> int:
    return (
        int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "big") % DIMENSIONS
    )


def _sparse(weights: dict[int, float]) -> SparseVector:
    return SparseVector(dict(sorted(weights.items())), DIMENSIONS)


def fit(texts: list[str], cfg: Bm25Config) -> list[SparseVector]:
    """BM25 document vectors for a whole corpus (idf and avgdl are corpus-global)."""
    tokenize = Tokenizer(cfg)
    counts = [Counter(term_dim(t) for t in tokenize(text)) for text in texts]
    n = len(counts)
    avgdl = sum(sum(c.values()) for c in counts) / max(n, 1)
    df = Counter(dim for c in counts for dim in c)
    idf = {dim: math.log(1 + (n - d + 0.5) / (d + 0.5)) for dim, d in df.items()}
    vectors = []
    for c in counts:
        dl = sum(c.values())
        norm = cfg.k1 * (1 - cfg.b + cfg.b * dl / avgdl) if avgdl else cfg.k1
        vectors.append(
            _sparse({d: idf[d] * tf * (cfg.k1 + 1) / (tf + norm) for d, tf in c.items()})
        )
    return vectors


def query_vector(text: str, cfg: Bm25Config) -> SparseVector | None:
    """Term counts of the query; None when nothing is left after tokenizing."""
    counts = Counter(term_dim(t) for t in Tokenizer(cfg)(text))
    return _sparse({d: float(n) for d, n in counts.items()}) if counts else None
