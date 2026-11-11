import math

from expert_knowledge_core import bm25
from expert_knowledge_core.bm25 import Bm25Config

CFG = Bm25Config()
TEXTS = [
    "sleep deprivation explains the shaking hands",
    "attention problems and sleep",
    "the radiator is new",
]


def test_inner_product_is_the_bm25_score():
    docs = bm25.fit(TEXTS, CFG)
    query = bm25.query_vector("sleep deprivation", CFG)
    assert query is not None
    scores = [float(query.to_numpy() @ d.to_numpy()) for d in docs]
    assert scores[0] > scores[1] > scores[2] == 0
    # by hand for the first document: idf(sleep) + idf(deprivation), each with tf = 1
    n, avgdl = 3, sum(len(bm25.Tokenizer(CFG)(t)) for t in TEXTS) / 3
    dl = len(bm25.Tokenizer(CFG)(TEXTS[0]))
    norm = CFG.k1 * (1 - CFG.b + CFG.b * dl / avgdl)

    def idf(df):
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    expected = sum(idf(df) * (CFG.k1 + 1) / (1 + norm) for df in (2, 1))
    assert math.isclose(scores[0], expected, rel_tol=1e-5)


def test_a_query_of_stopwords_has_no_vector():
    assert bm25.query_vector("the and of", CFG) is None


def test_stemming_matches_inflections():
    query = bm25.query_vector("shake", CFG)
    assert query is not None
    doc = bm25.fit(["shaking hands"], CFG)[0]
    assert float(query.to_numpy() @ doc.to_numpy()) > 0
    assert Bm25Config(stemmer=None).stemmer is None


def test_unknown_config_keys_are_rejected():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Bm25Config.model_validate({"k2": 1.0})
