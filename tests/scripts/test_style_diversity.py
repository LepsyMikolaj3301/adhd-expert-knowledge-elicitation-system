"""Tests for eval_style_diversity.py: the metrics and the grouping, with a fake embedder."""

import json

import eval_style_diversity as esd
import numpy as np


def test_stylometry_measures_where_chips_stand_and_lists():
    head = esd.stylometry(["⟦h1⟧⟦h2⟧: Plain prose follows here. Nothing else to add."])
    assert head["first_chip_position"] == 0 and head["chips_per_sentence"] == 1.0
    assert head["sentences_with_chip"] == 0.5
    items = esd.stylometry(["- one thing ⟦h1⟧.\n- another thing.\n- a third."])
    assert items["list_lines"] == 1.0 and items["words_per_sentence"] < 4
    late = esd.stylometry(["A long opening sentence with many words before ⟦h1⟧ appears."])
    assert late["first_chip_position"] > 0.5


def test_groups_by_model_and_persona_file():
    models = {"SYN-003": "qwen3.8:27b", "SYN-021": "gpt-oss:20b", "SYN-031": "qwen3.8:27b"}
    assert esd.group_of(1, models) == "claude"
    assert esd.group_of(3, models) == "qwen3.8 (one-line persona)"
    assert esd.group_of(21, models) == "gpt-oss"
    assert esd.group_of(31, models) == "qwen3.8 (persona file)"


def test_analyse_averages_similarity_by_group_pair(tmp_path):
    (tmp_path / "documents").mkdir()
    texts = {1: "Same words here.", 2: "Same words here.", 21: "Totally different style!"}
    for e, text in texts.items():
        doc = {
            "session_id": f"DOC-SYN-{e:04d}",
            "responses": [
                {"vignette_id": v, "answers": {q: text for q in esd.OPEN}} for v in esd.ANCHORS
            ],
        }
        (tmp_path / "documents" / f"DOC-SYN-{e:04d}.json").write_text(json.dumps(doc))
    (tmp_path / "manifest.json").write_text(
        json.dumps({"answer_models": {"SYN-021": "gpt-oss:20b"}})
    )

    def embed(batch):  # identical texts get identical vectors, the others an orthogonal one
        return [[1.0, 0.0] if t.startswith("Same") else [0.0, 1.0] for t in batch]

    result = esd.analyse(tmp_path, embed)
    pairs = result["similarity"]["pairs"]
    assert pairs["claude x claude"] == 1.0 and pairs["claude x gpt-oss"] == 0.0
    assert np.isclose(result["similarity"]["all"], 1 / 3, atol=1e-3)
    assert result["stylometry_by_group"]["gpt-oss"]["experts"] == [21]
