"""Retrieval-quality regression on the frozen silver snapshot, without and with an oracle.

The real retrievers (expert_knowledge_rag) run against the seeded schema with the frozen bge-m3
query vectors, and are scored with the offline evaluations' metrics (scripts/rag/expert_metrics.py):
recall@k, hit@k, MRR, nDCG, token-budget recall, and the ceiling (the best recall any 4 units could
reach). Relevance is claim based; a claim is held by the units listed in queries.json `covers`.

  no oracle   the retrievers as the application uses them
  oracle (a)  the ceiling: what the labels allow at best, so recall can be read as a share of it
  oracle (b)  the filter: retrieval restricted to the vignettes the relevant claims come from

Baselines live in tests/fixtures/retrieval_silver/baseline.json. After an intended change:
    UPDATE_RETRIEVAL_BASELINE=1 uv run pytest -m regression -s
Every run prints the table, and writes data/eval/regression/<time>.json where data/eval exists.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

import pytest
from expert_metrics import Item, ceiling, score_query

from expert_knowledge_rag import ExpertFilter, ExpertQuestionRetriever, PatientTextRetriever

pytestmark = [pytest.mark.integration, pytest.mark.regression]

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "tests" / "fixtures" / "retrieval_silver" / "baseline.json"
REPORTS = ROOT / "data" / "eval" / "regression"
UPDATE = bool(os.environ.get("UPDATE_RETRIEVAL_BASELINE"))

TOLERANCE = 0.02  # frozen vectors and a deterministic BM25: drift should be 0; this absorbs ties
HEADLINE = ("recall@4", "hit@4", "mrr", "ndcg@10", "recall@500t", "recall@4/ceiling")
LABELS = ("claim_ids", "pooled_ids")  # the original labels, and the pooled (completed) ones
SYNTHETIC = ExpertFilter(include_synthetic=True)  # everything in silver is synthetic


def items(docs) -> list[Item]:
    return [Item(d.metadata["unit_ids"], d.page_content, [d.page_content]) for d in docs]


def question_retriever(store, frozen, *, oracle: list[str] | None = None, **options):
    flt = ExpertFilter(include_synthetic=True, vignettes=oracle) if oracle else SYNTHETIC
    return ExpertQuestionRetriever(store=store, embeddings=frozen, filter=flt, k=10, **options)


# name -> (retriever options, uses the oracle filter, merges notes)
QUESTION_SETTINGS = {
    "question/hybrid": ({}, False, True),  # the default of the library
    "question/hybrid/no-merge": ({"merge_shared": False}, False, False),  # what the backend uses
    "question/dense/no-merge": ({"search": "dense", "merge_shared": False}, False, False),
    "question/bm25/no-merge": ({"search": "bm25", "merge_shared": False}, False, False),
    "question/hybrid/oracle-filter": ({}, True, True),
    "question/hybrid/no-merge/oracle-filter": ({"merge_shared": False}, True, False),
}


@pytest.fixture(scope="module")
def runs(silver, silver_store, frozen):
    """Per setting: the ranked items of every question (and patient text)."""
    queries = silver[2]
    out: dict[str, list[tuple[dict, list[Item]]]] = {}
    for name, (options, oracle, _) in QUESTION_SETTINGS.items():
        out[name] = [
            (
                q,
                items(
                    question_retriever(
                        silver_store, frozen, oracle=q["vignettes"] if oracle else None, **options
                    ).invoke(q["question"])
                ),
            )
            for q in queries["questions"]
        ]
    patient = []
    for p in queries["patients"]:
        flt = ExpertFilter(include_synthetic=True, exclude_vignettes=p["exclude"])
        retriever = PatientTextRetriever(store=silver_store, embeddings=frozen, filter=flt, k=10)
        patient.append((p, items(retriever.invoke(p["text"]))))
    out["patient/cues"] = patient
    return out


def mean_scores(ranked: list[tuple[dict, list[Item]]], covers: dict, labels: str) -> dict:
    scores = [score_query(r, q[labels if labels in q else "claim_ids"], covers) for q, r in ranked]
    scores = [s for s in scores if s]  # queries whose claims no unit holds count for nothing
    return {key: mean(s[key] for s in scores) for key in scores[0]} | {"queries": len(scores)}


@pytest.fixture(scope="module")
def scored(silver, runs):
    covers = {c: set(units) for c, units in silver[2]["covers"].items()}
    table: dict[str, dict[str, dict]] = {}
    for name, ranked in runs.items():
        label_sets = ("claim_ids",) if name.startswith("patient") else LABELS
        table[name] = {labels: mean_scores(ranked, covers, labels) for labels in label_sets}
    return table


@pytest.fixture(scope="module")
def label_ceilings(silver):
    queries, covers = silver[2], {c: set(u) for c, u in silver[2]["covers"].items()}
    out = {}
    for labels in LABELS:
        values = []
        for q in queries["questions"]:
            wanted = {c: covers[c] for c in q[labels] if covers[c]}
            if wanted:
                values.append(ceiling(wanted, 4))
        out[labels] = mean(values)
    return out


@pytest.fixture(scope="module", autouse=True)
def report(scored, label_ceilings):
    yield
    print("\n\nretrieval regression, silver snapshot (mean over queries)")
    print(f"{'setting':<42}{'labels':<11}" + "".join(f"{m:>17}" for m in HEADLINE))
    for name, by_labels in scored.items():
        for labels, row in by_labels.items():
            print(f"{name:<42}{labels:<11}" + "".join(f"{row[m]:>17.3f}" for m in HEADLINE))
    print(f"mean ceiling@4: {label_ceilings}")
    if REPORTS.parent.is_dir():  # only where the evaluations are kept (data/ is not in git)
        REPORTS.mkdir(exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        (REPORTS / f"{stamp}.json").write_text(
            json.dumps({"scores": scored, "ceilings": label_ceilings}, indent=1, sort_keys=True)
        )
    if UPDATE:
        BASELINE.write_text(
            json.dumps({"scores": scored, "ceilings": label_ceilings}, indent=1, sort_keys=True)
            + "\n"
        )
        print(f"baseline written to {BASELINE}")


@pytest.fixture(scope="module")
def baseline():
    if UPDATE:
        return None
    if not BASELINE.exists():
        pytest.fail("no baseline: UPDATE_RETRIEVAL_BASELINE=1 uv run pytest -m regression -s")
    return json.loads(BASELINE.read_text())


# --- no oracle: nothing got worse than the frozen baseline -------------------------------------


@pytest.mark.parametrize("setting", [*QUESTION_SETTINGS, "patient/cues"])
@pytest.mark.parametrize("labels", LABELS)
def test_no_headline_metric_fell_below_its_baseline(setting, labels, scored, baseline):
    if baseline is None:
        pytest.skip("writing the baseline")
    if labels not in scored[setting]:
        pytest.skip("patient texts have one label set")
    now, then = scored[setting][labels], baseline["scores"][setting][labels]
    assert now["queries"] == then["queries"], "the labels changed: refreeze and rebaseline"
    fell = {m: (then[m], now[m]) for m in HEADLINE if now[m] < then[m] - TOLERANCE}
    assert not fell, f"{setting} [{labels}] (baseline, now): {fell}"


def test_a_sane_retriever_finds_the_pooled_claims(scored):
    """Absolute floors, independent of the baseline, so a bad rebaseline cannot hide a collapse."""
    row = scored["question/hybrid/no-merge"]["pooled_ids"]
    assert row["hit@4"] >= 0.8 and row["mrr"] >= 0.5 and row["ndcg@10"] >= 0.4, row
    # patient texts search the cue keys and their labels are weak (offline: recall@4 about 0.004)
    assert scored["patient/cues"]["claim_ids"]["hit@4"] >= 0.1, scored["patient/cues"]


def test_hybrid_beats_the_weaker_single_search(scored):
    pooled = {
        m: scored[f"question/{m}/no-merge"]["pooled_ids"]["ndcg@10"]
        for m in ("hybrid", "dense", "bm25")
    }
    assert pooled["hybrid"] >= min(pooled["dense"], pooled["bm25"]), pooled


# --- oracle (a): the ceiling -------------------------------------------------------------------


@pytest.mark.parametrize(
    "setting", [n for n, (_, _, merges) in QUESTION_SETTINGS.items() if not merges]
)
@pytest.mark.parametrize("labels", LABELS)
def test_recall_never_exceeds_the_ceiling_of_four_units(setting, labels, silver, runs):
    covers = {c: set(u) for c, u in silver[2]["covers"].items()}
    for q, ranked in runs[setting]:
        s = score_query(ranked, q[labels], covers)
        if s:
            assert s["recall@4"] <= s["ceiling@4"] + 1e-9, q["question"]


@pytest.mark.parametrize("labels", LABELS)
def test_the_labels_and_the_unit_coverage_did_not_drift(labels, label_ceilings, baseline):
    if baseline is None:
        pytest.skip("writing the baseline")
    assert label_ceilings[labels] == pytest.approx(baseline["ceilings"][labels], abs=1e-9)


# --- oracle (b): knowing the vignettes -----------------------------------------------------------


@pytest.mark.parametrize("merged", ["", "/no-merge"])
def test_knowing_the_vignettes_never_hurts(merged, scored):
    plain = scored[f"question/hybrid{merged}"]["pooled_ids"]
    oracle = scored[f"question/hybrid{merged}/oracle-filter"]["pooled_ids"]
    print(f"oracle gap{merged}: recall@4 {oracle['recall@4'] - plain['recall@4']:+.3f}")
    assert oracle["recall@4"] >= plain["recall@4"] - 0.01
    assert oracle["hit@4"] >= plain["hit@4"] - 0.01


@pytest.mark.parametrize("setting", [n for n in QUESTION_SETTINGS if n.endswith("oracle-filter")])
def test_the_oracle_filter_only_returns_units_of_its_vignettes(setting, runs, silver):
    vignette_of = {u["id"]: u["vignette_id"] for u in silver[0]["units"]}
    for q, ranked in runs[setting]:
        found = {vignette_of[u] for item in ranked for u in item.unit_ids}
        assert found <= set(q["vignettes"]), q["question"]
