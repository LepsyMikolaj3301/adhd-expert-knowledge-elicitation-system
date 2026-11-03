import json

import pytest
import screen_reddit_posts as screen
from make_fixtures import Rejected

SENT = "I put off the start again and then the deadline was suddenly here, so I was late. "


class FakeModel:
    """Answers by post: ids starting with 'g' are good own accounts, 't' are tips, 'x' is broken."""

    name = "fake"

    def __init__(self):
        self.calls = 0

    def generate(self, req):
        self.calls += 1
        pid = req.key.split(":")[1]
        if pid.startswith("x"):
            return "not json"
        kind, fit, eps = ("own_struggle", 5, 2) if pid.startswith("g") else ("advice_or_tips", 2, 0)
        return json.dumps(
            dict(kind=kind, episodes=eps, subtlety=3, trait="task_initiation", fit=fit, reason="r")
        )


def write_pool(path, ids):
    rows = [{"id": i, "title": "T", "text": SENT * 20, "label": "adhd"} for i in ids]
    path.write_text("\n".join(json.dumps(r) for r in rows))


def run(tmp_path, ids, model, *extra):
    pool = tmp_path / "pool.jsonl"
    write_pool(pool, ids)
    return screen.main(
        ["--pool", str(pool), "--out", str(tmp_path / "s.jsonl")]
        + ["--shortlist", str(tmp_path / "short.jsonl"), "--cache", str(tmp_path / "c")]
        + ["--retries", "0", *extra],
        gen=model,
    )


def test_check_screen_rejects_bad_replies():
    good = dict(kind="own_struggle", episodes=2, subtlety=3, trait="none", fit=5, reason="r")
    assert screen.check_screen(json.dumps(good))["fit"] == 5
    for patch in ({"kind": "poem"}, {"fit": 6}, {"episodes": True}, {"trait": "x"}, {"reason": ""}):
        with pytest.raises(Rejected):
            screen.check_screen(json.dumps({**good, **patch}))


def test_prefilter_drops_other_people_and_advice_titles():
    assert not screen.prefilter("Then my husband said I was late again.", "")
    assert not screen.prefilter("I was late.", "Tips for mornings?")
    assert screen.prefilter("I was late again.", "Late again")


def test_screen_labels_shortlists_and_resumes(tmp_path):
    model = FakeModel()
    assert run(tmp_path, ["g1", "t1", "x1"], model) == 0
    labelled = [json.loads(line) for line in (tmp_path / "s.jsonl").read_text().splitlines()]
    assert {r["id"] for r in labelled} == {"g1", "t1"}  # x1 never validated: not written
    short = [json.loads(line) for line in (tmp_path / "short.jsonl").read_text().splitlines()]
    assert [r["id"] for r in short] == ["g1"] and short[0]["label"] == "adhd"
    first_calls = model.calls
    run(tmp_path, ["g1", "t1"], model)  # resume: both already labelled
    assert model.calls == first_calls
