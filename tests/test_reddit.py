import json

import make_fixtures
import pytest
from elicitation_schema import MAX_WORDS, MIN_WORDS, Vignette
from leak_terms import find_leaks
from reddit_posts import clean_post, load_pool, pick_posts, trait_score

SENT = "I put off the start again and then the deadline was suddenly here, so I was late. "


def post(extra=""):
    return extra + (SENT * 20)


def test_clean_post_drops_sentences_never_rewrites():
    raw = SENT * 8 + "My ADHD is bad. " + "See https://example.com now. " + SENT * 8
    cleaned = clean_post(raw)
    assert cleaned and "ADHD" not in cleaned and "https" not in cleaned
    assert find_leaks(cleaned) == []
    assert all(s in raw for s in cleaned.split(". ") if s)  # only whole original sentences


def test_clean_post_word_limits():
    assert clean_post("Too short to use.") is None
    cleaned = clean_post(post())
    assert cleaned and MIN_WORDS <= len(cleaned.split()) <= MAX_WORDS


def test_pool_loading_and_trait_pick(tmp_path):
    rows = [
        {"id": "a", "title": "Late again", "selftext": post(), "label": "adhd"},
        {"id": "b", "body": post(), "label": "control"},  # not an ADHD case: skipped
        {"id": "c", "text": "short"},  # too short: skipped
        {"id": "d", "text": "Nothing relevant here. " * 40},
    ]
    path = tmp_path / "pool.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows))
    posts = load_pool(path)
    assert {p.id for p in posts} == {"a", "d"}
    best = pick_posts(posts, "time_estimation", 1, set(), seed=1)
    assert [p.id for p in best] == ["a"] and trait_score(best[0].text, "time_estimation") >= 2
    assert pick_posts(posts, "time_estimation", 1, {"a"}, seed=1) == []


def run_reddit(tmp_path, *extra, source="reddit"):
    from test_make_fixtures import FakeGenerator

    pool = tmp_path / "pool.jsonl"
    tangent = "Anyway I went off on a tangent again, the point is I lost my train of thought. "
    pool.write_text(json.dumps({"id": "r1", "text": post(tangent * 3), "label": "adhd"}))
    gen = FakeGenerator()
    out = tmp_path / "out"
    code = make_fixtures.main(
        ["--out", str(out), "--source", source, "--persona-source", "ollama"]
        + ["--answer-source", "ollama", "--retries", "0", "--reddit-pool", str(pool)]
        + list(extra),
        persona_gen=gen,
        answer_gen=gen,
    )
    return code, out / source / "bronze"


def test_reddit_source_has_only_real_posts(tmp_path):
    code, tier_dir = run_reddit(tmp_path, "--reddit-vignettes", "1", "--n-documents", "0")
    assert code == 0
    real = [Vignette.model_validate_json(p.read_text()) for p in tier_dir.glob("vignettes/V*.json")]
    assert len(real) == 1 and real[0].design.origin == "real_text"
    assert real[0].design.source_ref == "reddit:r1" and real[0].design.track == "text_analysis"
    assert real[0].framing == "forum_post"
    manifest = json.loads((tier_dir / "manifest.json").read_text())
    assert manifest["source"] == "reddit" and manifest["tier"] == "bronze"


def test_n_documents_zero_writes_vignettes_only(tmp_path):
    code, tier_dir = run_reddit(tmp_path, "--reddit-vignettes", "1", "--n-documents", "0")
    assert code == 0 and list(tier_dir.glob("vignettes/V*.json"))
    assert not list(tier_dir.glob("documents/*.json"))


def test_reddit_posts_need_the_reddit_source(tmp_path):
    with pytest.raises(SystemExit, match="--source reddit"):
        run_reddit(tmp_path, "--reddit-vignettes", "1", source="synthetic")
