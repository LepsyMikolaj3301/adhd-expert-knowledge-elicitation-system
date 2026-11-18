"""The backend writes findings records; expert-knowledge-rag reads them. This is the one place that
sees both: it fails when the record the application builds drifts from what the package packs.

The package's own tests can't import the backend, so they use `example_record`; here that example
is checked against `findings.record_from_lines`, the path the application takes after review.
"""

from collections import defaultdict

from app.knowledge import findings
from expert_knowledge_core.example import VIGNETTE, example_record
from expert_knowledge_core.notes import pack_block
from expert_knowledge_core.records import is_readable
from expert_knowledge_rag.documents import build_documents
from expert_knowledge_rag.ranking import UnitHit


def stored(record: dict) -> dict:
    """The record as ingestion stores it: units are named by their highlight (`h1`) or `case`,
    not by the long ids `build_units` gives them (app.knowledge.ingest.load; the ingested
    document is checked against the real thing in tests/api/test_api_expert_rag.py)."""
    units = [{**u, "id": u["highlight"] or findings.CASE} for u in record["units"]]
    return {**record, "units": units}


def backend_record() -> dict:
    example = example_record("S1", "X1")
    lines: dict[str, list[dict]] = defaultdict(list)
    for s in example["sentences"]:
        lines[s["question_id"]].append(
            {"text": s["text"], "targets": s["targets"], "assigned_by": s["assigned_by"]}
        )
    response = findings.Response(
        vignette_id="V001",
        vignette_version=1,
        answers={q: "\n".join(line["text"] for line in ls) for q, ls in lines.items()},
        highlights=[
            findings.Highlight(h["chip"], h["text"], (h["span"][0], h["span"][1]), h["direction"])
            for h in example["highlights"]
            if h["chip"] is not None  # every example highlight has a chip
        ],
        rating=None,
        insufficient_information=True,
    )
    return stored(findings.record_from_lines(
        response, dict(lines), findings.expert_highlights(response.highlights), "S1", "X1",
        None, "personal_journal", "adult",
    ))  # fmt: skip


def test_the_record_the_application_builds_is_one_the_package_reads():
    record = backend_record()
    assert is_readable(record)
    assert record["version"] == findings.FINDINGS_VERSION


def test_the_example_is_cut_into_units_exactly_as_the_backend_cuts_it():
    record, example = backend_record(), example_record("S1", "X1")
    assert [u["id"] for u in record["units"]] == [u["id"] for u in example["units"]]
    for built, expected in zip(record["units"], example["units"], strict=True):
        for key in ("kind", "highlight", "direction", "sentences", "context", "body", "i1", "i3"):
            assert built[key] == expected[key], (built["id"], key)


def test_packing_the_backends_record_equals_packing_the_example():
    record, example = backend_record(), example_record("S1", "X1")
    for group in (["h3", "h1"], ["h4"], ["case"], ["h2", "h1", "h3"]):
        assert pack_block(record, group) == pack_block(example, group)


def test_documents_are_built_from_the_backends_record():
    record = backend_record()
    hits = [
        UnitHit(
            id=f"S1-V001-{u['id']}", session_id="S1", expert_id="X1", vignette_id="V001",
            vignette_version=1, kind=u["kind"], highlight_id=None, direction=u["direction"],
            embed_text=u["i1"], score=1.0 - n / 10,
        )
        for n, u in enumerate(record["units"])
    ]  # fmt: skip
    docs = build_documents(hits, {"S1": record})
    assert docs and all(d.page_content.startswith("Teaching case V001") for d in docs)
    assert {u for d in docs for u in d.metadata["unit_ids"]} == {h.id for h in hits}


def test_the_example_vignette_text_holds_every_highlight():
    for h in example_record()["highlights"]:
        assert VIGNETTE[h["span"][0] : h["span"][1]] == h["text"]
