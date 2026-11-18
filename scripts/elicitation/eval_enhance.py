# ruff: noqa: E501  (report strings)
"""Does the enhancer (the proofreading's fuller-sentences pass) keep the clinician's meaning and voice?
Compares Answer_enhance.v1 (shown the cited passages) with v2 (not shown them, worked examples), each
under the old reply checks (chips, length) and the new ones (also leak and voice,
backend/app/proofread/enhance.py).

Usage:
  python scripts/elicitation/eval_enhance.py --calibrate
      no model: the new checks over the v1 replies already in the proofread scale fixture
  python scripts/elicitation/eval_enhance.py --run-dir data/eval/enhance/<name> [--model qwen3.5:9b] [--others 200]
      both prompts on a stratified sample (every note-style answer + --others random ones), replies to
      replies.jsonl (resumable), the metrics to results.json / report.md, blinded judge blocks to judge/blocks/
  python scripts/elicitation/eval_enhance.py --run-dir data/eval/enhance/<name> --aggregate
      after the judges wrote judge/<model>/<block>.json: un-blinds, adds their grades to the report

Input is each raw answer of data/fixtures_chips_scale (silver) after the garbage pass. The grammar pass
is skipped in both arms (no LanguageTool needed; it changed at most one word per answer there).
Needs Ollama with --model for the run.
"""

import argparse
import asyncio
import json
import random
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "rag"))

from expert_metrics import bootstrap, weighted_kappa  # noqa: E402

from app.ollama import chat_json  # noqa: E402
from app.prompts import load_prompt  # noqa: E402
from app.proofread import enhance, garbage, grammar  # noqa: E402
from app.vignettes.questions import QUESTIONS, render_question  # noqa: E402

RAW = ROOT / "data/fixtures_chips_scale/synthetic/silver"
PROOFREAD = ROOT / "data/fixtures_chips_scale_proofread/synthetic/silver"
ARMS = {"v1": "Answer_enhance.v1", "v2": "Answer_enhance.v2"}
JUDGE_PROMPT = "Enhance_fidelity_judge.v1"
BLOCK = 20
NEW_ONLY = {"leak", "voice"}  # the reasons the old checks did not have
# A note: a chip followed by a dash or colon ("⟦h1⟧ - late start"), or two or more list lines.
_NOTE = re.compile(r"⟦h\d+⟧\s*[-–:]")
_LIST = re.compile(r"^\s*(?:[-*•+?]|\d+[.)])\s+", re.MULTILINE)


@dataclass(frozen=True)
class Item:
    key: str  # session/vignette/question
    question: str
    answer: str  # after the garbage pass
    quotes: dict[int, str]

    @property
    def note(self) -> bool:
        return is_note(self.answer)


def is_note(text: str) -> bool:
    return bool(_NOTE.search(text)) or len(_LIST.findall(text)) >= 2


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, " ".join(a.split()), " ".join(b.split())).ratio()


def bucket(sim: float) -> str:
    return "unchanged" if sim >= 0.98 else "light" if sim >= 0.85 else "heavy"


def _vignette_text(folder: Path) -> dict[str, str]:
    out = {}
    for path in sorted((folder / "vignettes").glob("*.json")):
        data = json.loads(path.read_text())
        out[data["id"]] = data["text"]
    return out


def load_items(folder: Path = RAW) -> list[Item]:
    """Every open answer of the fixture, after the garbage pass, as the proofread job sees it."""
    vignettes = _vignette_text(folder)
    items = []
    for path in sorted((folder / "documents").glob("*.json")):
        doc = json.loads(path.read_text())
        for resp in doc["responses"]:
            quotes = {h["chip"]: h["text"] for h in resp.get("highlights", [])}
            protected = grammar.vocabulary(vignettes.get(resp["vignette_id"], ""))
            for qid, text in sorted(resp["answers"].items()):
                if qid == "Q4" or not text or not text.strip():
                    continue
                kept, _ = garbage.drop_garbage(text, protected)
                if kept.strip():
                    items.append(
                        Item(
                            f"{doc['session_id']}/{resp['vignette_id']}/{qid}",
                            render_question(QUESTIONS[qid], None),
                            kept,
                            quotes,
                        )
                    )
    return items


def sample(items: list[Item], others: int, seed: int = 1) -> list[Item]:
    """Every note-style answer, plus `others` of the rest at random."""
    notes = [i for i in items if i.note]
    rest = [i for i in items if not i.note]
    picked = random.Random(seed).sample(rest, min(others, len(rest)))
    return sorted(notes + picked, key=lambda i: i.key)


# --- calibration: the new checks on the v1 replies already made ----------------------------------


def calibrate(raw: Path = RAW, proofread: Path = PROOFREAD) -> dict:
    by_key = {i.key: i for i in load_items(raw)}
    counts: dict[str, Counter] = defaultdict(Counter)
    shown = []
    for path in sorted((proofread / "proofread").glob("*.json")):
        session = path.stem
        for vid, questions in json.loads(path.read_text()).items():
            for qid, row in questions.items():
                if row.get("passes", {}).get("enhanced") is not True:
                    continue
                item = by_key.get(f"{session}/{vid}/{qid}")
                original = item.answer if item else row["original"]
                quotes = item.quotes if item else {}
                text = " ".join(row["proposed"].split("\n"))
                b = bucket(similarity(original, text))
                why = enhance.rejection(json.dumps({"answer": text}), original, quotes)
                counts[b]["accepted_v1"] += 1
                counts[b][why or "kept"] += 1
                if why in NEW_ONLY:
                    shown.append({"key": f"{session}/{vid}/{qid}", "bucket": b, "why": why,
                                  "leaked": enhance.leaked(text, original, quotes),
                                  "original": original, "reply": text})
    return {"buckets": {b: dict(c) for b, c in counts.items()}, "rejected": shown}


def print_calibration(result: dict, show: str) -> None:
    print("bucket      accepted by v1  -> leak   voice  (share refused by the new checks)")
    for b in ("unchanged", "light", "heavy"):
        c = result["buckets"].get(b, {})
        n = c.get("accepted_v1", 0)
        refused = c.get("leak", 0) + c.get("voice", 0)
        print(f"{b:<11} {n:>14}  {c.get('leak', 0):>6} {c.get('voice', 0):>6}  ({refused / max(n, 1):.1%})")
    for row in result["rejected"]:
        if show == "all" or row["bucket"] in show.split(","):
            print(f"\n== {row['key']} [{row['bucket']}] {row['why']} {row['leaked']}\nORIG:  {row['original']}\nREPLY: {row['reply']}")


# --- the run --------------------------------------------------------------------------------------


def prompt_for(arm: str, item: Item):
    prompt = load_prompt(ARMS[arm])
    if arm == "v1":
        citations = "\n".join(f'⟦h{c}⟧: "{t}"' for c, t in sorted(item.quotes.items()))
        return prompt.fill(QUESTION=item.question, ANSWER=item.answer, CITATIONS=citations or "(none)")
    return prompt.fill(QUESTION=item.question, ANSWER=item.answer)


async def run(items: list[Item], run_dir: Path, model: str) -> None:
    path = run_dir / "replies.jsonl"
    done = set()
    if path.exists():
        done = {(r["key"], r["arm"]) for r in map(json.loads, path.read_text().splitlines())}
    todo = [(arm, i) for arm in ARMS for i in items if (i.key, arm) not in done]
    print(f"{len(todo)} calls to {model} ({len(done)} already done)")
    with path.open("a") as out:
        for n, (arm, item) in enumerate(todo, 1):
            prompt = prompt_for(arm, item)
            raw, error = "", None
            for _attempt in range(3):
                try:
                    raw = await chat_json(model, prompt.system, prompt.user, {"seed": 1, **enhance.OPTIONS})
                    error = None
                    break
                except httpx.HTTPStatusError as exc:
                    # e.g. "token repeat limit reached": the model looped. Counted, not fatal; in the
                    # app the pipeline records the enhancement as unavailable.
                    error = exc.response.text[:200]
                    await asyncio.sleep(2)
            row = {"key": item.key, "arm": arm, "raw": raw, **({"error": error} if error else {})}
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
            if n % 20 == 0:
                print(f"  {n}/{len(todo)}")


# --- metrics --------------------------------------------------------------------------------------


def judged_rows(items: list[Item], replies: list[dict]) -> list[dict]:
    """One row per (answer, arm): the reply, why the new checks refuse it, and its measures."""
    by_key = {i.key: i for i in items}
    rows = []
    for r in replies:
        item = by_key.get(r["key"])
        if item is None:
            continue
        why = "model_error" if r.get("error") else enhance.rejection(r["raw"], item.answer, item.quotes)
        data = enhance.parse_json_object(r["raw"]) or {}
        text = data.get("answer", "").strip() if isinstance(data.get("answer"), str) else ""
        sim = similarity(item.answer, text) if text else 0.0
        rows.append({
            "key": item.key, "arm": r["arm"], "note": item.note, "why": why, "text": text,
            "old_ok": why is None or why in NEW_ONLY, "new_ok": why is None,
            "bucket": bucket(sim) if text else None,
            "leak": len(enhance.leaked(text, item.answer, item.quotes)) >= enhance.LEAK_WORDS if text else False,
            "voice": bool(text) and enhance.narrated(text) > enhance.narrated(item.answer),
            "new_words": len(enhance._content(text) - enhance._content(item.answer)) if text else 0,
            "length": len(text.split()) / max(len(item.answer.split()), 1) if text else 0.0,
        })
    return rows


def _rate(values: list[bool]) -> dict:
    if not values:
        return {"n": 0}
    mean, lo, hi = bootstrap([float(v) for v in values])
    return {"n": len(values), "rate": mean, "ci": [lo, hi]}


def cell(rows: list[dict], checks: str) -> dict:
    ok = "old_ok" if checks == "old" else "new_ok"
    accepted = [r for r in rows if r[ok]]
    return {
        "answers": len(rows),
        "accepted": _rate([r[ok] for r in rows]),
        "refused_because": dict(Counter(r["why"] for r in rows if not r[ok])),
        "buckets": dict(Counter(r["bucket"] for r in accepted)),
        "leak": _rate([r["leak"] for r in accepted]),
        "voice": _rate([r["voice"] for r in accepted]),
        "new_words_mean": sum(r["new_words"] for r in accepted) / max(len(accepted), 1),
        "length_mean": sum(r["length"] for r in accepted) / max(len(accepted), 1),
    }


def metrics(rows: list[dict]) -> dict:
    out = {}
    for subset, keep in (("all", lambda r: True), ("notes", lambda r: r["note"])):
        for arm in ARMS:
            for checks in ("old", "new"):
                out[f"{subset}/{arm}/{checks}"] = cell([r for r in rows if r["arm"] == arm and keep(r)], checks)
    return out


# --- judging --------------------------------------------------------------------------------------


def write_blocks(items: list[Item], rows: list[dict], run_dir: Path, seed: int = 1) -> int:
    """Every reply the old checks accept and that changed the answer, both arms mixed and blinded."""
    by_key = {i.key: i for i in items}
    pairs = [r for r in rows if r["old_ok"] and r["bucket"] != "unchanged"]
    random.Random(seed).shuffle(pairs)
    key = {}
    blocks = run_dir / "judge" / "blocks"
    blocks.mkdir(parents=True, exist_ok=True)
    template = load_prompt(JUDGE_PROMPT)
    for start in range(0, len(pairs), BLOCK):
        parts = []
        for n, r in enumerate(pairs[start : start + BLOCK], start + 1):
            pid = f"p{n:03d}"
            key[pid] = {"key": r["key"], "arm": r["arm"]}
            item = by_key[r["key"]]
            passages = "\n".join(f'⟦h{c}⟧: "{t}"' for c, t in sorted(item.quotes.items())) or "(none)"
            parts.append(
                f"<pair id=\"{pid}\">\n<question>{item.question}</question>\n<original>\n{item.answer}\n</original>\n"
                f"<passages>\n{passages}\n</passages>\n<edited>\n{r['text']}\n</edited>\n</pair>"
            )
        prompt = template.fill(PAIRS="\n\n".join(parts))
        name = f"block_{start // BLOCK + 1:02d}"
        (blocks / f"{name}.md").write_text(f"# System\n\n{prompt.system}\n\n# User\n\n{prompt.user}\n")
    (run_dir / "judge" / "key.json").write_text(json.dumps(key, indent=1))
    return len(pairs)


def load_grades(run_dir: Path) -> dict[str, dict[str, dict]]:
    """judge model -> pair id -> grade."""
    out: dict[str, dict[str, dict]] = {}
    for folder in sorted((run_dir / "judge").iterdir()):
        if folder.is_dir() and folder.name != "blocks":
            grades = {}
            for path in sorted(folder.glob("*.json")):
                grades.update(json.loads(path.read_text()))
            out[folder.name] = grades
    return out


def judge_summary(rows: list[dict], key: dict, grades: dict[str, dict[str, dict]]) -> dict:
    by = {(r["key"], r["arm"]): r for r in rows}
    out: dict = {}
    for judge, g in grades.items():
        for subset in ("all", "notes"):
            for arm in ARMS:
                for checks in ("old", "new"):
                    ok = "old_ok" if checks == "old" else "new_ok"
                    picked = [
                        grade for pid, grade in g.items()
                        if pid in key and key[pid]["arm"] == arm
                        and by[(key[pid]["key"], arm)][ok]
                        and (subset == "all" or by[(key[pid]["key"], arm)]["note"])
                    ]
                    out[f"{judge}/{subset}/{arm}/{checks}"] = {
                        "meaning_same": _rate([x.get("meaning") == "same" for x in picked]),
                        "voice_ok": _rate([bool(x.get("voice_ok")) for x in picked]),
                        "fuller_mean": sum(int(x.get("fuller", 1)) for x in picked) / max(len(picked), 1),
                        "meaning": dict(Counter(x.get("meaning") for x in picked)),
                    }
    judges = sorted(grades)
    if len(judges) >= 2:
        a, b = grades[judges[0]], grades[judges[1]]
        both = sorted(set(a) & set(b))
        out["agreement"] = {
            "judges": judges[:2], "pairs": len(both),
            "meaning_same": sum((a[p].get("meaning") == "same") == (b[p].get("meaning") == "same") for p in both) / max(len(both), 1),
            "voice_ok": sum(bool(a[p].get("voice_ok")) == bool(b[p].get("voice_ok")) for p in both) / max(len(both), 1),
            "fuller_kappa": weighted_kappa([int(a[p].get("fuller", 1)) for p in both], [int(b[p].get("fuller", 1)) for p in both], levels=3) if both else None,
        }
    return out


# --- the report -----------------------------------------------------------------------------------


def _pct(r: dict) -> str:
    return "–" if not r.get("n") else f"{r['rate']:.1%} [{r['ci'][0]:.1%}, {r['ci'][1]:.1%}] (n={r['n']})"


def decision(m: dict, j: dict | None) -> list[str]:
    """The rule of the plan: on note-style answers, v2 with the new checks against v1 with the old."""
    new = m["notes/v2/new"]
    lines = [
        f"- leaks among accepted ≤ 1%: {new['leak'].get('rate', 0):.1%} → {'yes' if new['leak'].get('rate', 0) <= 0.01 else 'no'}",
        f"- voice switches among accepted ≤ 1%: {new['voice'].get('rate', 0):.1%} → {'yes' if new['voice'].get('rate', 0) <= 0.01 else 'no'}",
        f"- acceptance ≥ 75%: {new['accepted'].get('rate', 0):.1%} → {'yes' if new['accepted'].get('rate', 0) >= 0.75 else 'no'}",
    ]
    if j:
        for judge in sorted({k.split("/")[0] for k in j if k != "agreement"}):
            a, b = j[f"{judge}/notes/v2/new"], j[f"{judge}/notes/v1/old"]
            same = a["meaning_same"].get("rate", 0) >= b["meaning_same"].get("rate", 0)
            voice = a["voice_ok"].get("rate", 0) > b["voice_ok"].get("rate", 0)
            lines.append(f"- {judge}: meaning kept {b['meaning_same'].get('rate', 0):.1%} → {a['meaning_same'].get('rate', 0):.1%} (not lower: {'yes' if same else 'no'}); voice kept {b['voice_ok'].get('rate', 0):.1%} → {a['voice_ok'].get('rate', 0):.1%} (higher: {'yes' if voice else 'no'})")
    else:
        lines.append("- judges: not yet graded (run the judges, then --aggregate)")
    return lines


def report(m: dict, j: dict | None, meta: dict) -> str:
    out = [f"# Enhancer v1 vs v2 ({meta['model']})", "",
           f"{meta['answers']} answers ({meta['notes']} note-style), seed {meta['seed']}. Grammar pass skipped in both arms.", ""]
    for subset in ("notes", "all"):
        out += [f"## {subset}", "", "| arm / checks | accepted | leak (of accepted) | voice switch | unchanged / light / heavy | new words | length × |", "|---|---|---|---|---|---|---|"]
        for arm in ARMS:
            for checks in ("old", "new"):
                c = m[f"{subset}/{arm}/{checks}"]
                b = c["buckets"]
                out.append(f"| {arm} / {checks} | {_pct(c['accepted'])} | {_pct(c['leak'])} | {_pct(c['voice'])} | {b.get('unchanged', 0)} / {b.get('light', 0)} / {b.get('heavy', 0)} | {c['new_words_mean']:.1f} | {c['length_mean']:.2f} |")
        out.append("")
        if j:
            out += ["| judge / arm / checks | meaning kept | voice kept | fuller (1-3) | meaning counts |", "|---|---|---|---|---|"]
            for k, v in j.items():
                if k != "agreement" and k.split("/")[1] == subset:
                    judge, _, arm, checks = k.split("/")
                    out.append(f"| {judge} / {arm} / {checks} | {_pct(v['meaning_same'])} | {_pct(v['voice_ok'])} | {v['fuller_mean']:.2f} | {v['meaning']} |")
            out.append("")
    if j and "agreement" in j:
        a = j["agreement"]
        kappa = f"{a['fuller_kappa']:.2f}" if a["fuller_kappa"] is not None else "–"
        out += [f"Judge agreement ({' vs '.join(a['judges'])}, {a['pairs']} pairs): meaning kept {a['meaning_same']:.0%}, voice {a['voice_ok']:.0%}, fuller weighted kappa {kappa}.", ""]
    out += ["## Decision (note-style answers, v2 + new checks against v1 + old checks)", "", *decision(m, j), ""]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--show", default="unchanged,light", help="calibrate: buckets whose refusals to print (or 'all')")
    ap.add_argument("--run-dir", type=Path)
    ap.add_argument("--aggregate", action="store_true")
    ap.add_argument("--model", default="qwen3.5:9b")
    ap.add_argument("--others", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args(argv)

    if args.calibrate:
        print_calibration(calibrate(), args.show)
        return 0
    if not args.run_dir:
        ap.error("--run-dir is needed unless --calibrate")
    args.run_dir.mkdir(parents=True, exist_ok=True)
    items = sample(load_items(), args.others, args.seed)
    if not args.aggregate:
        asyncio.run(run(items, args.run_dir, args.model))
    replies = [json.loads(line) for line in (args.run_dir / "replies.jsonl").read_text().splitlines()]
    rows = judged_rows(items, replies)
    m = metrics(rows)
    j = None
    if args.aggregate:
        key = json.loads((args.run_dir / "judge" / "key.json").read_text())
        j = judge_summary(rows, key, load_grades(args.run_dir))
    else:
        print(f"{write_blocks(items, rows, args.run_dir, args.seed)} pairs to judge in {args.run_dir / 'judge' / 'blocks'}")
    meta = {"model": args.model, "answers": len(items), "notes": sum(i.note for i in items), "seed": args.seed}
    (args.run_dir / "results.json").write_text(json.dumps({"meta": meta, "metrics": m, "judges": j, "rows": rows}, indent=1, ensure_ascii=False))
    (args.run_dir / "report.md").write_text(report(m, j, meta))
    print(report(m, j, meta))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
