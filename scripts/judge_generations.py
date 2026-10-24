"""LLM-as-judge scoring of the answers in a generation run (scripts/eval_generation.py).

Usage: python scripts/judge_generations.py --run-dir data/eval/runs/<ts> --judge-model M
       python scripts/judge_generations.py --run-dir ... --export-blind
       python scripts/judge_generations.py --run-dir ... --import-blind RESULTS --judge-name NAME

Every answer is graded with the rubric in rag_common.JUDGE_RUBRIC (correctness, faithfulness,
citation quality, completeness 1-5, abstention, pass) against the reference answer and the
context the model saw. Writes <run-dir>/judgments.json.

--judge-model grades with a local Ollama model. Avoid a model that is also a contestant.
--export-blind writes judge_blind.json (rubric + one prompt per answer, model names replaced by
shuffled labels) and judge_key.json for an external judge, e.g. a Claude agent. That judge
writes RESULTS as {"<label>": {<judgment object>}, ...}; --import-blind validates it and maps
the labels back.
"""

import argparse
import json
import random
import secrets
from datetime import UTC, datetime
from pathlib import Path

from rag_common import JUDGE_RUBRIC, OllamaChat, judge_prompt, parse_judgment, write_json


def write_judgments(run_dir: Path, judge: str, judgments: list[dict]) -> None:
    write_json(
        run_dir / "judgments.json",
        {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "judge": judge,
            "rubric": JUDGE_RUBRIC,
            "judgments": judgments,
        },
    )
    print(f"wrote {run_dir / 'judgments.json'} ({len(judgments)} judgments)")


def local_judge(run: dict, args: argparse.Namespace) -> list[dict]:
    chat = OllamaChat(args.judge_model, think=False, num_predict=400)
    judgments = []
    for g in run["generations"]:
        prompt = judge_prompt(run["questions"][g["id"]], g["answer"])
        try:
            judgment = parse_judgment(chat.chat(JUDGE_RUBRIC, prompt)[0])
        except Exception as e:  # keep going: one bad reply must not stop the run
            print(f"FAILED  {g['model']}  {g['id']}: {type(e).__name__}: {e}")
            continue
        judgments.append({"id": g["id"], "model": g["model"], **judgment})
        print(f"{g['model']:18} {g['id']}  pass={judgment['pass']}")
    return judgments


def export_blind(run: dict, run_dir: Path) -> None:
    generations = list(run["generations"])
    random.shuffle(generations)
    key, items = {}, []
    for g in generations:
        label = secrets.token_hex(4)
        key[label] = {"id": g["id"], "model": g["model"]}
        items.append(
            {"label": label, "prompt": judge_prompt(run["questions"][g["id"]], g["answer"])}
        )
    write_json(run_dir / "judge_blind.json", {"rubric": JUDGE_RUBRIC, "items": items})
    write_json(run_dir / "judge_key.json", key)
    print(f"wrote {run_dir / 'judge_blind.json'} ({len(items)} items) and judge_key.json")


def import_blind(run_dir: Path, results_path: Path) -> list[dict]:
    key = json.loads((run_dir / "judge_key.json").read_text())
    results = json.loads(results_path.read_text())
    judgments = []
    for label, target in key.items():
        if label not in results:
            print(f"MISSING {label}  {target['model']}  {target['id']}")
            continue
        judgments.append({**target, **parse_judgment(json.dumps(results[label]))})
    return judgments


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--judge-model", help="local Ollama judge model")
    mode.add_argument("--export-blind", action="store_true")
    mode.add_argument("--import-blind", type=Path, metavar="RESULTS")
    parser.add_argument("--judge-name", default="external", help="judge recorded on import")
    args = parser.parse_args()

    run = json.loads((args.run_dir / "generations.json").read_text())
    if args.export_blind:
        export_blind(run, args.run_dir)
    elif args.import_blind:
        write_judgments(
            args.run_dir, args.judge_name, import_blind(args.run_dir, args.import_blind)
        )
    else:
        write_judgments(args.run_dir, f"ollama:{args.judge_model}", local_judge(run, args))


if __name__ == "__main__":
    main()
