"""Retrieval as more experts answer the same vignettes: eval_scale_retrieval.py curves, pinned.

The 32-expert scale snapshot (local only, under data/: see tests/integration/conftest.py) is seeded
into a throwaway schema, and scripts/rag/eval_scale_retrieval.py `evaluate` runs on it with the
question vectors frozen next to the snapshot (`--freeze-queries`), so nothing calls a model.
Pools of n = 2, 10, 20, 32 experts, k = 4 and 8. The curves (crowding@k on the anchor vignettes,
expert coverage, vignette precision, original-label claim recall) are compared with
tests/fixtures/retrieval_scale/baseline.json, and so is the first n at which each one goes wrong.

This pins today's behaviour, including the known crowding (crowding@8 on anchors reaches 0.5 between
10 and 20 experts): a change that makes it come earlier, or makes any point worse, fails. After an
intended change, or after rebuilding the snapshot:
    UPDATE_SCALE_BASELINE=1 uv run pytest -m scale -s
Every run prints the curves and the latency; where data/eval exists it writes
data/eval/regression/scale-<time>.json and .md (the report of eval_scale_retrieval.py).
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from eval_scale_retrieval import CURVE_RULES, curves, evaluate, pool_facts, report, summary

pytestmark = [pytest.mark.integration, pytest.mark.regression, pytest.mark.scale]

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "tests" / "fixtures" / "retrieval_scale" / "baseline.json"
REPORTS = ROOT / "data" / "eval" / "regression"
UPDATE = bool(os.environ.get("UPDATE_SCALE_BASELINE"))

NS = [2, 10, 20, 32]
KS = [4, 8]
TOLERANCE = 0.02  # frozen vectors and a deterministic BM25: drift should be 0; this absorbs ties
LOWER_IS_BETTER = {name for name in CURVE_RULES if name.startswith("crowding")}


def plain(data):
    """Through JSON, so int keys compare with the baseline's string keys."""
    return json.loads(json.dumps(data))


@pytest.fixture(scope="module")
def run(dsn, scale_schema, scale_store, scale_frozen, scale_snapshot):
    facts = pool_facts(dsn, scale_schema)
    assert len(facts["experts"]) >= max(NS), facts["experts"]
    questions = scale_snapshot["questions"]
    results = evaluate(scale_store, scale_frozen, facts, questions, NS, KS)
    return {
        "snapshot_sha": scale_snapshot["snapshot_sha"],
        "data": summary(scale_schema, facts, questions, None, results),
        "curves": plain(curves(results, NS, KS)),
    }


@pytest.fixture(scope="module", autouse=True)
def print_and_save(run):
    yield
    print("\n\nretrieval at scale (mean per pool size n; problem = first n that goes wrong)")
    print(f"{'curve':<22}{'k':>3}" + "".join(f"{'n=' + str(n):>9}" for n in NS) + "   problem")
    for name, by_k in run["curves"].items():
        for k, c in by_k.items():
            cells = "".join(
                f"{c['mean'][str(n)] if c['mean'][str(n)] is not None else '-':>9}" for n in NS
            )
            print(f"{name:<22}{k:>3}{cells}   {c['problem_n'] or '-'}")
    ms = sorted(r["ms"] for r in run["data"]["results"])
    print(
        f"latency per search: p50 {ms[len(ms) // 2]:.0f} ms, p95 {ms[int(len(ms) * 0.95)]:.0f} ms"
    )
    if REPORTS.parent.is_dir():  # only where the evaluations are kept (data/ is not in git)
        REPORTS.mkdir(exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        (REPORTS / f"scale-{stamp}.json").write_text(json.dumps(run, indent=1))
        report(run["data"], NS, KS, REPORTS / f"scale-{stamp}.md")
    if UPDATE:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        keep = {"snapshot_sha": run["snapshot_sha"], "ns": NS, "ks": KS, "curves": run["curves"]}
        BASELINE.write_text(json.dumps(keep, indent=1, sort_keys=True) + "\n")
        print(f"baseline written to {BASELINE}")


@pytest.fixture(scope="module")
def baseline(run):
    if UPDATE:
        pytest.skip("writing the baseline")
    if not BASELINE.exists():
        pytest.fail("no baseline: UPDATE_SCALE_BASELINE=1 uv run pytest -m scale -s")
    base = json.loads(BASELINE.read_text())
    if base["snapshot_sha"] != run["snapshot_sha"]:
        pytest.skip(
            "the baseline is of another snapshot: UPDATE_SCALE_BASELINE=1 uv run pytest -m scale -s"
        )
    return base


# --- against the baseline -----------------------------------------------------------------------


@pytest.mark.parametrize("k", KS)
@pytest.mark.parametrize("curve", list(CURVE_RULES))
def test_no_point_of_the_curve_got_worse(curve, k, run, baseline):
    now, then = run["curves"][curve][str(k)], baseline["curves"][curve][str(k)]
    assert now["items"] == then["items"], "the question set changed: rebaseline"
    sign = -1 if curve in LOWER_IS_BETTER else 1
    worse = {
        n: (then["mean"][n], v)
        for n, v in now["mean"].items()
        if v is not None
        and then["mean"][n] is not None
        and sign * (v - then["mean"][n]) < -TOLERANCE
    }
    assert not worse, f"{curve} k={k} (baseline, now) per n: {worse}"


@pytest.mark.parametrize("k", KS)
@pytest.mark.parametrize("curve", [c for c, (_, _, rule) in CURVE_RULES.items() if rule])
def test_the_problem_does_not_come_earlier(curve, k, run, baseline):
    now, then = (
        run["curves"][curve][str(k)]["problem_n"],
        baseline["curves"][curve][str(k)]["problem_n"],
    )
    if then is None:
        assert now is None, f"{curve} k={k}: goes wrong at n={now}, the baseline never did"
    else:
        assert now is None or now >= then, (
            f"{curve} k={k}: goes wrong at n={now}, baseline n={then}"
        )


# --- floors, independent of the baseline (so a bad rebaseline cannot hide a collapse) ------------


def test_few_experts_retrieve_the_right_vignettes(run):
    c = run["curves"]
    for k in map(str, KS):
        assert c["precision_labelled"][k]["mean"]["2"] >= 0.5, c["precision_labelled"][k]
        assert c["precision_topic"][k]["mean"]["2"] >= 0.3, c["precision_topic"][k]


def test_downweighting_never_adds_crowding(run):
    c = run["curves"]
    for k in map(str, KS):
        on, off = c["crowding_anchor"][k]["mean"], c["crowding_anchor_off"][k]["mean"]
        assert all(on[n] <= off[n] + TOLERANCE for n in on if on[n] is not None), (on, off)


def test_several_experts_reach_the_top_k(run):
    cover = run["curves"]["coverage_anchor"]["8"]["mean"]
    assert all(v is not None and v > 0.25 for v in cover.values()), cover
