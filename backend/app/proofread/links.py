"""Which citations each line of an answer is about.

A line is what the author sees and links: the proofread answers have one sentence per line. A line
is `{text, targets, assigned_by}`; `targets` holds highlight ids (h1, i1) and `case`, and is empty
while nobody has linked the line.

The proofread job links every line in layers: chips, quoted words (`findings.link_text`), then
the classifier for the rest. While the author edits, `relink` keeps the links of lines that did not
change and links new or edited lines with the first two layers only. It never calls a model, so
saving stays fast and gives the same result every time.
"""

from typing import Any

from app.knowledge import classifier, findings

Line = dict[str, Any]


def lines_of(text: str) -> list[str]:
    return [line.strip() for line in text.split("\n") if line.strip()]


def link_lines(
    answers: dict[str, str], highlights: list[dict], vignette: str
) -> dict[str, list[Line]]:
    """The first two layers. Appends implicit highlights to `highlights`."""
    linked: dict[str, list[Line]] = {}
    for qid in sorted(answers):
        linked[qid] = []
        for text in lines_of(answers[qid]):
            targets, by = findings.link_text(text, highlights, vignette)
            linked[qid].append({"text": text, "targets": targets, "assigned_by": by})
    return linked


def as_sentences(linked: dict[str, list[Line]]) -> list[dict]:
    """The lines in the classifier's sentence shape (ids like Q1.3)."""
    return [
        {
            "id": f"{qid}.{idx}",
            "question_id": qid,
            "text": line["text"],
            "targets": list(line["targets"]),
            "assigned_by": line["assigned_by"],
        }
        for qid in sorted(linked)
        for idx, line in enumerate(linked[qid], 1)
    ]


async def classify_rest(
    linked: dict[str, list[Line]], highlights: list[dict], vignette: str
) -> dict[str, Any]:
    """The third layer: the classifier links what is left, `prev` and the `case` fallback
    included. Changes `linked` in place and returns how it went."""
    sentences = as_sentences(linked)
    left = findings.unresolved(sentences)
    labels, info = await classifier.classify(vignette, highlights, sentences, left)
    findings.apply_classification(sentences, labels)
    by_id = {s["id"]: s for s in sentences}
    for qid, lines in linked.items():
        for idx, line in enumerate(lines, 1):
            sentence = by_id[f"{qid}.{idx}"]
            line["targets"], line["assigned_by"] = sentence["targets"], sentence["assigned_by"]
    return {"left": len(left), "attempts": info["attempts"]}


def relink(
    old: list[Line],
    text: str,
    overrides: dict[str, list[str]],
    highlights: list[dict],
    vignette: str,
) -> list[Line]:
    """The lines of `text`, linked. For each line, the first that applies: the author's tags for
    it (`overrides`, by line text), the links of an old line with the same text, the chips and
    quoted words in it, or nothing."""
    before = {line["text"]: line for line in old}
    lines = []
    for line_text in lines_of(text):
        if line_text in overrides:
            targets, by = list(dict.fromkeys(overrides[line_text])), "expert"
        elif line_text in before:
            targets, by = list(before[line_text]["targets"]), before[line_text]["assigned_by"]
        else:
            targets, by = findings.link_text(line_text, highlights, vignette)
        lines.append({"text": line_text, "targets": targets, "assigned_by": by})
    return lines


def unlinked(lines: list[Line]) -> list[int]:
    """Positions (from 0) of the lines that still need a citation or `case`."""
    return [index for index, line in enumerate(lines) if not line["targets"]]
