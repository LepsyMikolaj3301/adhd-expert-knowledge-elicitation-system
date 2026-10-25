"""LLM-as-judge scoring of the answers in a generation run (scripts/eval_generation.py).

Usage: python scripts/judge_generations.py --run-dir data/eval/runs/<ts> --judge-model M
       python scripts/judge_generations.py --run-dir ... --export-blind [--parts N] [--models M ...]
       python scripts/judge_generations.py --run-dir ... --import-blind RESULTS... --judge-name N

Answers are graded per (question, context) item: the judge sees the question, the reference
answer, the context passages and every system's samples, and returns per-sample scores with the
rubric in rag_common.JUDGE_RUBRIC (correctness, faithfulness, citation quality, completeness 1-5,
abstention, pass) plus, per system, how consistent its samples were (consistency 1-5,
behaviour_changed, a note). Results are merged into <run-dir>/judgments.json, so a later round
(e.g. only a newly added model, via --models) adds to the earlier ones.

--judge-model grades with a local Ollama model. Avoid a model that is also a contestant.
--export-blind writes judge_blind_part<i>.json (rubric + items; model names replaced by labels
shuffled per item) and judge_key.json for an external judge, e.g. Claude agents. The judge writes
one RESULTS file per part as {"<item label>": {<reply object>}, ...}; --import-blind validates
the replies and maps the labels back.
"""

import argparse
import json
import random
import secrets
import string
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from rag_common import JUDGE_RUBRIC, OllamaChat, judge_prompt, parse_judgment, write_json


def grading_items(run: dict, models: list[str] | None) -> list[dict]:
    """One item per (question, context): {id, context, systems: {model: [(sample, answer)]}}."""
    groups: dict[tuple[str, str], dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for g in run["generations"]:
        if models is None or g["model"] in models:
            groups[(g["id"], g["context"])][g["model"]].append((g["sample"], g["answer"]))
    return [
        {"id": qid, "context": ctx, "systems": {m: sorted(s) for m, s in sorted(systems.items())}}
        for (qid, ctx), systems in sorted(groups.items())
    ]


def blind(item: dict) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Shuffled labels A, B, ... -> model, and label -> sample answers."""
    models = list(item["systems"])
    random.shuffle(models)
    labels = dict(zip(string.ascii_uppercase, models, strict=False))
    return labels, {lab: [a for _, a in item["systems"][m]] for lab, m in labels.items()}


def rows_from_reply(item: dict, labels: dict[str, str], parsed: dict) -> tuple[list, list]:
    samples, consistency = [], []
    for label, verdict in parsed.items():
        model = labels[label]
        key = {"id": item["id"], "model": model, "context": item["context"]}
        for (sample, _), judgment in zip(item["systems"][model], verdict["samples"], strict=True):
            samples.append({**key, "sample": sample, **judgment})
        consistency.append({**key, **{k: v for k, v in verdict.items() if k != "samples"}})
    return samples, consistency


def write_judgments(run_dir: Path, judge: str, samples: list[dict], consistency: list[dict]):
    path = run_dir / "judgments.json"
    old = json.loads(path.read_text()) if path.exists() else {}

    def merge(previous: list[dict], new: list[dict], fields: tuple[str, ...]) -> list[dict]:
        keys = {tuple(r[f] for f in fields) for r in new}
        return [r for r in previous if tuple(r[f] for f in fields) not in keys] + new

    write_json(
        path,
        {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "judge": sorted({*([j] if isinstance(j := old.get("judge", []), str) else j), judge}),
            "rubric": JUDGE_RUBRIC,
            "judgments": merge(
                old.get("judgments", []), samples, ("id", "model", "context", "sample")
            ),
            "consistency": merge(
                old.get("consistency", []), consistency, ("id", "model", "context")
            ),
        },
    )
    print(f"wrote {path} (+{len(samples)} sample judgments, +{len(consistency)} consistency)")


def local_judge(run: dict, args: argparse.Namespace) -> None:
    chat = OllamaChat(args.judge_model, think=False, num_predict=2000)
    samples, consistency = [], []
    for item in grading_items(run, args.models):
        q = run["questions"][item["id"]]
        labels, systems = blind(item)
        prompt = judge_prompt(q, q["contexts"][item["context"]], systems)
        try:
            parsed = parse_judgment(chat.chat(JUDGE_RUBRIC, prompt)[0], systems)
        except Exception as e:  # keep going: one bad reply must not stop the run
            print(f"FAILED  {item['id']} {item['context']}: {type(e).__name__}: {e}")
            continue
        s, c = rows_from_reply(item, labels, parsed)
        samples += s
        consistency += c
        print(f"{item['id']} {item['context']:9}  pass {sum(r['pass'] for r in s)}/{len(s)}")
    write_judgments(args.run_dir, f"ollama:{args.judge_model}", samples, consistency)


def export_blind(run: dict, args: argparse.Namespace) -> None:
    key, exported = {}, []
    for item in grading_items(run, args.models):
        q = run["questions"][item["id"]]
        labels, systems = blind(item)
        label = secrets.token_hex(4)
        key[label] = {**item, "labels": labels}
        prompt = judge_prompt(q, q["contexts"][item["context"]], systems)
        exported.append({"label": label, "id": item["id"], "prompt": prompt})
    # Parts of about equal size, never splitting one question's items.
    by_question: dict[str, list] = defaultdict(list)
    for e in exported:
        by_question[e.pop("id")].append(e)
    parts: list[list] = [[] for _ in range(args.parts)]
    for items in sorted(by_question.values(), key=lambda xs: -sum(len(x["prompt"]) for x in xs)):
        min(parts, key=lambda p: sum(len(x["prompt"]) for x in p)).extend(items)
    for i, part in enumerate(parts, 1):
        write_json(
            args.run_dir / f"judge_blind_part{i}.json", {"rubric": JUDGE_RUBRIC, "items": part}
        )
        print(f"wrote judge_blind_part{i}.json ({len(part)} items)")
    write_json(args.run_dir / "judge_key.json", key)


def import_blind(args: argparse.Namespace) -> None:
    key = json.loads((args.run_dir / "judge_key.json").read_text())
    results = {}
    for path in args.import_blind:
        results |= json.loads(path.read_text())
    samples, consistency = [], []
    for label, entry in key.items():
        if label not in results:
            print(f"MISSING {label}  {entry['id']} {entry['context']}")
            continue
        item = {k: entry[k] for k in ("id", "context")}
        item["systems"] = {m: [tuple(s) for s in v] for m, v in entry["systems"].items()}
        systems = {lab: [a for _, a in item["systems"][m]] for lab, m in entry["labels"].items()}
        try:
            parsed = parse_judgment(results[label], systems)
        except ValueError as e:
            print(f"INVALID {label}  {entry['id']} {entry['context']}: {e}")
            continue
        s, c = rows_from_reply(item, entry["labels"], parsed)
        samples += s
        consistency += c
    write_judgments(args.run_dir, args.judge_name, samples, consistency)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--judge-model", help="local Ollama judge model")
    mode.add_argument("--export-blind", action="store_true")
    mode.add_argument("--import-blind", type=Path, nargs="+", metavar="RESULTS")
    parser.add_argument("--models", nargs="+", help="only grade these models' answers")
    parser.add_argument("--parts", type=int, default=1, help="files to split --export-blind into")
    parser.add_argument("--judge-name", default="external", help="judge recorded on import")
    args = parser.parse_args()

    run = json.loads((args.run_dir / "generations.json").read_text())
    if args.export_blind:
        export_blind(run, args)
    elif args.import_blind:
        import_blind(args)
    else:
        local_judge(run, args)


if __name__ == "__main__":
    main()
