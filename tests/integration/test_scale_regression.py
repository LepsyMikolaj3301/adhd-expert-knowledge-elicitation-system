"""Retrieval as more experts answer the same vignettes: eval_scale_retrieval.py curves, pinned.

The answers of all 32 experts of tests/fixtures/scale_answers are ingested at test time into a
throwaway schema (tests/integration/conftest.py), and scripts/rag/eval_scale_retrieval.py `evaluate`
runs on it, the questions embedded by bge-m3 as the application embeds them. Pools of n = 2, 10,
20, 32 experts, k = 4 and 8. The curves (crowding@k on the anchor vignettes, expert coverage,
vignette precision, original-label claim recall) are compared with
tests/fixtures/retrieval_scale/baseline.json, and so is the first n at which each one goes wrong.

The `fixed` questions also run with the agreement grouping of fragments on (the groups are
recomputed for every pool, so a note counts the clinicians of that pool), with the near-duplicate
down-weighting on and off. The curves tell what the top k is crowded with: repeated fragments or
repeated case notes.

This pins today's behaviour, including the known crowding (crowding@8 on anchors reaches 0.5 at
10 experts): a change that makes it come earlier, or makes any point worse, fails. After an
intended change, after changing the fixture or the embedding model (the baseline names both):
    UPDATE_SCALE_BASELINE=1 uv run pytest -m scale -s
Every run prints the curves and the latency; where data/eval exists it writes
data/eval/regression/scale-<time>.json and .md (the report of eval_scale_retrieval.py).
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import chips_fixture
import numpy as np
import psycopg
import pytest
from eval_scale_retrieval import (
    CURVE_RULES,
    build_questions,
    curves,
    evaluate,
    pool_facts,
    report,
    summary,
)

pytestmark = [pytest.mark.integration, pytest.mark.regression, pytest.mark.scale]

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "tests" / "fixtures" / "retrieval_scale" / "baseline.json"
REPORTS = ROOT / "data" / "eval" / "regression"
UPDATE = bool(os.environ.get("UPDATE_SCALE_BASELINE"))

NS = [2, 10, 20, 32]
KS = [4, 8]
TOLERANCE = 0.02  # same model, deterministic BM25: drift ~0; absorbs ties and GPU/CPU noise
LOWER_IS_BETTER = {name for name in CURVE_RULES if name.startswith(("crowding", "case_"))}


def plain(data):
    """Through JSON, so int keys compare with the baseline's string keys."""
    return json.loads(json.dumps(data))


@pytest.fixture(scope="module")
def run(dsn, scale, scale_schema, scale_store, embedder, fixture_digest):
    facts = pool_facts(dsn, scale_schema)
    assert len(facts["experts"]) >= max(NS), facts["experts"]
    questions = build_questions(scale.queries, chips_fixture.load().vignettes)
    for q in questions:
        embedder.embed_query(q["question"])  # first, so the latency below is the database's
    try:
        results = evaluate(
            scale_store,
            embedder,
            facts,
            questions,
            NS,
            KS,
            grouping=lambda pool: chips_fixture.set_agreement_pool(dsn, scale_schema, pool),
        )
    finally:
        chips_fixture.set_agreement_pool(dsn, scale_schema, None)  # everyone's groups again
    return {
        "fixture": fixture_digest,
        "embedding_model": embedder.model,
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
        keep = {key: run[key] for key in ("fixture", "embedding_model", "curves")}
        keep |= {"ns": NS, "ks": KS}
        BASELINE.write_text(json.dumps(keep, indent=1, sort_keys=True) + "\n")
        print(f"baseline written to {BASELINE}")


@pytest.fixture(scope="module")
def baseline(run):
    if UPDATE:
        pytest.skip("writing the baseline")
    if not BASELINE.exists():
        pytest.fail("no baseline: UPDATE_SCALE_BASELINE=1 uv run pytest -m scale -s")
    base = json.loads(BASELINE.read_text())
    now = {key: run[key] for key in ("fixture", "embedding_model")}
    then = {key: base.get(key) for key in now}
    if now != then:
        pytest.fail(
            f"the baseline was measured on {then}, this run is {now}: "
            "UPDATE_SCALE_BASELINE=1 uv run pytest -m scale -s"
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


# --- the down-weighting and the grouping, measured ----------------------------------------------


def test_case_answers_of_different_experts_are_almost_never_near_duplicates(dsn, scale_schema):
    """Why the down-weighting does nothing here: the case answers of the experts to one vignette are
    alike (median cosine ~0.74) but 2 of 2500 pairs reach NEAR_DUPLICATE, none on an anchor
    vignette.
    If this fails the data now has copies, and the down-weighting has something to do."""
    from eval_scale_retrieval import ANCHORS

    from expert_knowledge_core.retrieval import NEAR_DUPLICATE

    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            f'SELECT vignette_id, embedding::text FROM "{scale_schema}".finding_units '
            "WHERE kind = 'case' ORDER BY vignette_id, expert_id"
        ).fetchall()
    by_vignette: dict[str, list[np.ndarray]] = {}
    for vignette, text in rows:
        v = np.asarray(text.strip("[]").split(","), dtype=np.float32)
        by_vignette.setdefault(vignette, []).append(v / np.linalg.norm(v))
    pairs = near = 0
    for vignette, vectors in by_vignette.items():
        m = np.stack(vectors)
        sims = (m @ m.T)[np.triu_indices(len(m), 1)]
        pairs += sims.size
        near += int((sims >= NEAR_DUPLICATE).sum())
        if vignette in ANCHORS:
            assert not (sims >= NEAR_DUPLICATE).any(), (vignette, float(sims.max()))
    assert near / pairs < 0.01, (near, pairs)


def test_the_crowding_of_anchors_is_mostly_case_notes_not_repeated_fragments(run):
    """What the top k is crowded with at 10+ experts (k=8): repeated case notes of the vignette (the
    experts' overall answers, which have no passage to group by), not fragments."""
    c = run["curves"]
    for n in ("10", "20", "32"):
        case = c["crowding_case_anchor"]["8"]["mean"][n]
        fragment = c["crowding_fragment_anchor"]["8"]["mean"][n]
        assert case > fragment, (n, case, fragment)


def test_down_weighting_changes_nothing_on_these_answers(run):
    c = run["curves"]
    for k in map(str, KS):
        on, off = c["crowding_case_anchor"][k]["mean"], c["crowding_case_anchor_nodw"][k]["mean"]
        assert on == off, (on, off)


def test_grouping_removes_repeated_passages_from_the_top_k(run):
    """By agreement group (a passage that several clinicians marked in different words is one):
    grouping never repeats more, and repeats clearly less once 10+ experts answer."""
    c = run["curves"]
    for k in map(str, KS):
        plain = c["crowding_passage_anchor"][k]["mean"]
        grouped = c["crowding_passage_anchor_grouped"][k]["mean"]
        assert all(grouped[n] <= plain[n] + TOLERANCE for n in plain), (k, plain, grouped)
        assert all(plain[n] - grouped[n] > 0.05 for n in ("10", "20", "32")), (k, plain, grouped)


def test_grouping_counts_many_more_clinicians_in_the_same_top_k(run):
    c = run["curves"]
    for k in map(str, KS):
        plain = c["clinicians_anchor"][k]["mean"]
        grouped = c["clinicians_anchor_grouped"][k]["mean"]
        assert all(grouped[n] >= plain[n] for n in plain), (plain, grouped)
        assert grouped["32"] > 2 * plain["32"], (plain, grouped)


def test_grouping_keeps_expert_coverage(run):
    """Coverage counts the first clinician of each note, so a grouped note is not credited for the
    others it carries: it may dip a little, it must not collapse."""
    c = run["curves"]
    for k in map(str, KS):
        plain, grouped = c["coverage_anchor"][k]["mean"], c["coverage_anchor_grouped"][k]["mean"]
        assert all(grouped[n] >= plain[n] - 0.15 for n in plain), (plain, grouped)


def test_agreement_groups_follow_the_pool(dsn, scale_schema, run):
    """The groups of the grouping variants are those of the pool's experts only (restored after)."""
    pool = run["data"]["facts"]["experts"][:3]
    try:
        group_of = chips_fixture.set_agreement_pool(dsn, scale_schema, pool)
        with psycopg.connect(dsn) as conn:
            sch = f'"{scale_schema}"'
            outside = conn.execute(
                f"SELECT count(*) FROM {sch}.fragment_group_members WHERE expert_id <> ALL(%s)",
                (pool,),
            ).fetchone()[0]
            answered = conn.execute(
                f"SELECT max(n_answered) FROM {sch}.fragment_groups"
            ).fetchone()[0]
        assert group_of and outside == 0 and answered <= len(pool)
    finally:
        everyone = chips_fixture.set_agreement_pool(dsn, scale_schema, None)
    assert len(everyone) > len(group_of)
