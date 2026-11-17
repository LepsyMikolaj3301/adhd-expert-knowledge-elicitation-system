"""The helpers of make_fixtures.py that the chip pipeline and the retrieval eval still import."""

import json

from make_fixtures import CHIP_SOURCE, Rejected, fixture_dir, write_json


def test_chip_fixtures_live_in_their_own_folder(tmp_path):
    root = tmp_path / "fixtures"
    assert fixture_dir("silver", CHIP_SOURCE, root) == tmp_path / "fixtures_chips/synthetic/silver"
    assert fixture_dir("silver", "synthetic", root) == root / "synthetic" / "silver"


def test_write_json_makes_the_folders_and_sorts_the_keys(tmp_path):
    path = tmp_path / "a" / "b.json"
    write_json(path, {"b": 1, "a": "é"})
    text = path.read_text()
    assert text.endswith("}\n") and text.index('"a"') < text.index('"b"')
    assert json.loads(text) == {"a": "é", "b": 1}


def test_a_rejected_output_carries_its_reason():
    assert str(Rejected("names from the persona")) == "names from the persona"
