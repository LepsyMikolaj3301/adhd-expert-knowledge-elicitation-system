# ruff: noqa: E501  (long prompt and SQL strings)
"""The final evaluation's question set: new clinician questions, new patient texts and out-of-scope
questions, with the notes a good answer must draw on (oracle units and key points), on `chips_scale`.

Usage: python scripts/rag/make_final_queries.py [--allow C03 P07 ...]

Runs its stages in order and stops with "awaiting" whenever a Claude agent has to answer through the
inbox (data/inbox/requests/<key>.md -> data/inbox/responses/<key>.json); rerun after the reply.
  1. questions  prompts/Final_eval_questions.v1.md: the author sees the 24 vignettes and their design
                (planted cues, other explanations) and the elicitation questions, never a clinician's
                notes, so a question cannot echo them. Checked: anchored passages are in their
                vignette, a patient text names no diagnosis or medication (leak_terms), and no item
                repeats a run of 6+ words of a vignette (--allow accepts named items after a look).
  2. pool       per item, the candidate notes: the top POOL_K units of hybrid, dense and bm25, each
                with and without fragment grouping (the package's retrievers), plus design targets
                (units whose highlight overlaps the anchored passage or a planted cue of the item's
                traits, the DESIGN_CAP nearest by bge-m3), at most POOL_CAP, shown in a hashed order.
                Needs `chips_scale` seeded (scripts/db/chips_fixture.py seed --schema chips_scale)
                and Ollama with bge-m3.
  3. oracle     prompts/Final_eval_oracle.v1.md, LABEL_PART items per request: key points, each with
                the units that make it, direction, condition, grade 2/1, and whether the notes answer
                the item at all.
  4. fixture    tests/fixtures/final_eval/queries.json + manifest.json (committed; data/ is not).
A key point plays the part of a claim: covers = {key point id: unit ids}, so expert_metrics.score_query
scores recall@k, MRR, nDCG@10 and recall@500t over these items unchanged.
"""

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "scripts" / "db"), str(ROOT / "scripts" / "elicitation")]

import chips_fixture  # noqa: E402
import psycopg  # noqa: E402
from expert_rag_lib import PATIENT_QUESTION, SEARCHES, make_retriever  # noqa: E402
from leak_terms import find_leaks  # noqa: E402
from llm_clients import AwaitingResponse, GenRequest, InboxGenerator  # noqa: E402
from prompt_loader import load_prompt  # noqa: E402

from app.vignettes.questions import QUESTIONS  # noqa: E402
from expert_knowledge_rag import ExpertKnowledgeStore, default_embeddings  # noqa: E402

SCHEMA = "chips_scale"
INBOX = ROOT / "data/inbox"
WORK = ROOT / "data/eval/final"
OUT = ROOT / "tests/fixtures/final_eval"
N_CLINICIAN, N_ANCHORED, N_PATIENT, N_OUT = 30, 18, 15, 5
POOL_K, POOL_CAP, DESIGN_CAP, LABEL_PART = 10, 60, 20, 7
LONGEST_SHARED_RUN = 5  # words an item may share in a row with a vignette
DIRECTIONS = {"raises", "lowers", "neutral", "mixed"}
ANSWERABLE = {"yes", "partly", "no"}
KIND_PREFIX = {"clinician": "C", "patient": "P", "out_of_scope": "X"}


# --- 1. questions ------------------------------------------------------------------------------


def load_vignettes() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted((chips_fixture.FIXTURE / "documents").glob("DOC-*.json")):
        for v in json.loads(path.read_text())["vignettes"]:
            out.setdefault(v["id"], v)
    return dict(sorted(out.items()))


def trait_name(trait: str) -> str:
    """`distractibility: small detour ...` -> `distractibility`."""
    return trait.split(":")[0].strip()


def vignette_block(vignettes: dict[str, dict]) -> str:
    blocks = []
    for v in vignettes.values():
        d = v["design"]
        lines = [f"### {v['id']} ({v['framing']}, {d['population']}): {d['purpose']}"]
        lines += [
            f'- sign, {trait_name(c["trait"])} ({c["strength"]}): "{c["quote"]}"'
            for c in d["planted_cues"]
        ]
        lines += [
            f'- other explanation: "{c["quote"]}" ({c["alternative_explanation"]})'
            for c in d.get("confounders") or []
        ]
        lines.append(f'Text: "{v["text"]}"')
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def question_request(vignettes: dict[str, dict]) -> GenRequest:
    asked = "\n".join(f"- {q}: {QUESTIONS[q].text}" for q in ("Q1", "Q2", "Q3", "Q5"))
    p = load_prompt("Final_eval_questions.v1").fill(
        ELICITATION=asked,
        VIGNETTES=vignette_block(vignettes),
        N_CLINICIAN=N_CLINICIAN,
        N_ANCHORED=N_ANCHORED,
        N_PATIENT=N_PATIENT,
        N_OUT=N_OUT,
    )
    return GenRequest(key="final:questions", system=p.system, user=p.user, json_mode=True)


WORD = re.compile(r"[a-z0-9']+")


def runs_of(text: str, n: int) -> set[tuple[str, ...]]:
    words = WORD.findall(text.lower())
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def with_ids(raw: list[dict]) -> list[dict]:
    counters: dict[str, int] = {}
    items = []
    for r in raw:
        prefix = KIND_PREFIX[r["kind"]]
        counters[prefix] = counters.get(prefix, 0) + 1
        items.append({"id": f"{prefix}{counters[prefix]:02d}", **r})
    return items


def item_text(item: dict) -> str:
    return item.get("text") or item["question"]


def problems_of(items: list[dict], vignettes: dict[str, dict]) -> dict[str, list[str]]:
    shared = set().union(*(runs_of(v["text"], LONGEST_SHARED_RUN + 1) for v in vignettes.values()))
    out: dict[str, list[str]] = {}
    for item in items:
        p = []
        text = item_text(item)
        if runs_of(text, LONGEST_SHARED_RUN + 1) & shared:
            p.append(f"repeats {LONGEST_SHARED_RUN + 1}+ words of a vignette")
        if item["kind"] == "clinician" and item.get("anchor"):
            a = item["anchor"]
            if (
                a["vignette"] not in vignettes
                or a["passage"] not in vignettes[a["vignette"]]["text"]
            ):
                p.append(f"anchor passage not found in {a['vignette']}")
        if item["kind"] == "patient":
            if leaks := find_leaks(text):
                p.append(f"names {leaks}")
            missing = [
                q["quote"]
                for q in item.get("signs", []) + item.get("other_explanations", [])
                if q["quote"] not in text
            ]
            if missing:
                p.append(f"quotes not in the text: {missing}")
            words = len(text.split())
            if not 60 <= words <= 240:
                p.append(f"{words} words")
        if p:
            out[item["id"]] = p
    return out


def questions_stage(vignettes: dict[str, dict], allow: set[str]) -> list[dict]:
    raw = json.loads(InboxGenerator(INBOX).generate(question_request(vignettes)))["items"]
    items = with_ids(raw)
    counts = {k: sum(i["kind"] == k for i in items) for k in KIND_PREFIX}
    print(f"questions: {counts}")
    problems = {k: v for k, v in problems_of(items, vignettes).items() if k not in allow}
    if problems:
        for k, v in problems.items():
            print(
                f"  {k}: {'; '.join(v)}  | {item_text(next(i for i in items if i['id'] == k))[:120]}"
            )
        raise SystemExit(
            "fix these items in the response (or accept them with --allow ID ...) and rerun"
        )
    return items


# --- 2. pool -----------------------------------------------------------------------------------


def design_units(conn, item: dict, vignettes: dict[str, dict]) -> list[str]:
    """Units whose highlight overlaps the item's anchored passage or a planted cue of its traits."""
    spans: list[tuple[str, int, int]] = []
    anchor = item.get("anchor")
    if anchor:
        text = vignettes[anchor["vignette"]]["text"]
        start = text.find(anchor["passage"])
        spans.append((anchor["vignette"], start, start + len(anchor["passage"])))
    traits = set(item.get("traits") or []) | {s["trait"] for s in item.get("signs", [])}
    for v in vignettes.values():
        for cue in v["design"]["planted_cues"]:
            if trait_name(cue["trait"]) in traits and (start := v["text"].find(cue["quote"])) >= 0:
                spans.append((v["id"], start, start + len(cue["quote"])))
    units: list[str] = []
    for vignette, a, b in spans:
        rows = conn.execute(
            f"SELECT u.id FROM {SCHEMA}.finding_units u JOIN {SCHEMA}.highlights h ON h.id = u.highlight_id "
            "WHERE h.vignette_id = %s AND h.span && int4range(%s, %s) ORDER BY u.id",
            (vignette, a, b),
        ).fetchall()
        units += [r[0] for r in rows if r[0] not in units]
    return units


def nearest(conn, ids: list[str], vector: list[float], n: int) -> list[str]:
    if not ids:
        return []
    rows = conn.execute(
        f"SELECT id FROM {SCHEMA}.finding_units WHERE id = ANY(%s) "
        "ORDER BY embedding <=> CAST(%s AS vector) LIMIT %s",
        (ids, "[" + ",".join(f"{x:.7f}" for x in vector) + "]", n),
    ).fetchall()
    return [r[0] for r in rows]


def hashed(item_id: str, units: list[str]) -> list[str]:
    return sorted(units, key=lambda u: hashlib.md5(f"{item_id}|{u}".encode()).hexdigest())


def pool_stage(items: list[dict], vignettes: dict[str, dict], dsn: str, base_url: str) -> dict:
    path = WORK / "pools.json"
    pools = json.loads(path.read_text()) if path.exists() else {}
    todo = [i for i in items if i["id"] not in pools]
    if not todo:
        return pools
    store = ExpertKnowledgeStore(dsn, schema=SCHEMA)
    embeddings = default_embeddings(base_url=base_url)
    with psycopg.connect(dsn) as conn:
        conn.read_only = True
        for item in todo:
            text = item_text(item)
            best: dict[str, tuple[int, str]] = {}
            sources: dict[str, list[str]] = {}
            for search in SEARCHES:
                for grouped in (False, True):
                    name = f"{search}{'+group' if grouped else ''}"
                    retriever = make_retriever(
                        store,
                        embeddings,
                        patient=item["kind"] == "patient",
                        k=POOL_K,
                        search=search,
                        group_fragments=grouped,
                    )
                    for rank, doc in enumerate(retriever.invoke(text)):
                        for u in doc.metadata["unit_ids"]:
                            best[u] = min(best.get(u, (rank, u)), (rank, u))
                            sources.setdefault(u, []).append(name)
            design = nearest(
                conn,
                design_units(conn, item, vignettes),
                embeddings.embed_query(text),
                DESIGN_CAP,
            )
            for u in design:
                sources.setdefault(u, []).append("design")
            chosen = list(dict.fromkeys(design))
            for u in sorted(best, key=best.get):
                if len(chosen) >= POOL_CAP:
                    break
                if u not in chosen:
                    chosen.append(u)
            order = hashed(item["id"], chosen)
            pools[item["id"]] = {
                "aliases": {f"U{n}": u for n, u in enumerate(order, 1)},
                "sources": {u: sorted(set(sources[u])) for u in order},
                "retrieved": len(best),
                "design": len(design),
            }
            print(
                f"pool {item['id']}: {len(order)} notes ({len(best)} retrieved, {len(design)} by design)"
            )
            WORK.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(pools, indent=1))
    return pools


# --- 3. oracle ---------------------------------------------------------------------------------


def unit_texts(dsn: str, ids: list[str]) -> dict[str, str]:
    with psycopg.connect(dsn) as conn:
        conn.read_only = True
        rows = conn.execute(
            f"SELECT id, embed_text FROM {SCHEMA}.finding_units WHERE id = ANY(%s)", (ids,)
        ).fetchall()
    return dict(rows)


def oracle_requests(items: list[dict], pools: dict, dsn: str) -> list[GenRequest]:
    texts = unit_texts(dsn, sorted({u for p in pools.values() for u in p["aliases"].values()}))
    reqs = []
    for part, start in enumerate(range(0, len(items), LABEL_PART), 1):
        blocks = []
        for item in items[start : start + LABEL_PART]:
            if item["kind"] == "patient":
                head = f'## {item["id"]} (patient text)\nPatient text: "{item["text"]}"'
            else:
                head = f"## {item['id']} (clinician question)\nQuestion: {item['question']}"
            notes = "\n\n".join(
                f"[{alias}] {texts[u]}" for alias, u in pools[item["id"]]["aliases"].items()
            )
            blocks.append(f"{head}\n\nCandidate notes:\n\n{notes}")
        p = load_prompt("Final_eval_oracle.v1").fill(BLOCK="\n\n---\n\n".join(blocks))
        reqs.append(
            GenRequest(key=f"final:oracle:{part}", system=p.system, user=p.user, json_mode=True)
        )
    return reqs


def oracle_stage(items: list[dict], pools: dict, dsn: str) -> dict[str, dict]:
    inbox, labels, waiting = InboxGenerator(INBOX), {}, []
    for req in oracle_requests(items, pools, dsn):
        try:
            labels |= json.loads(inbox.generate(req))["items"]
        except AwaitingResponse as e:
            waiting.append(str(e))
    if waiting:
        raise AwaitingResponse("; ".join(waiting))
    errors = []
    for item in items:
        got = labels.get(item["id"])
        aliases = pools[item["id"]]["aliases"]
        if got is None:
            errors.append(f"{item['id']}: no labels")
            continue
        if got.get("answerable") not in ANSWERABLE:
            errors.append(f"{item['id']}: answerable {got.get('answerable')!r}")
        for n, kp in enumerate(got.get("key_points", []), 1):
            bad = [u for u in kp.get("units", []) if u not in aliases]
            if bad or not kp.get("units"):
                errors.append(f"{item['id']} point {n}: units {bad or 'missing'}")
            if kp.get("direction") not in DIRECTIONS or kp.get("grade") not in (1, 2):
                errors.append(
                    f"{item['id']} point {n}: direction/grade {kp.get('direction')!r}/{kp.get('grade')!r}"
                )
    if errors:
        raise SystemExit("bad oracle replies:\n  " + "\n  ".join(errors))
    return labels


# --- 4. fixture --------------------------------------------------------------------------------


def fixture_item(item: dict, pool: dict, label: dict) -> dict:
    aliases = pool["aliases"]
    key_points = [
        {
            "id": f"{item['id']}#{n}",
            "text": kp["text"],
            "direction": kp["direction"],
            "condition": kp.get("condition"),
            "grade": kp["grade"],
            "unit_ids": sorted(aliases[u] for u in kp["units"]),
        }
        for n, kp in enumerate(label.get("key_points", []), 1)
    ]
    out = {
        "id": item["id"],
        "kind": item["kind"],
        "question": PATIENT_QUESTION if item["kind"] == "patient" else item["question"],
        "answerable": label["answerable"],
        "key_points": key_points,
        "labeller_note": label.get("note"),
        "pool": sorted(aliases.values()),
    }
    if item["kind"] == "patient":
        out |= {k: item.get(k) for k in ("text", "framing", "signs", "other_explanations")}
        out["patient_text"] = out.pop("text")
    elif item["kind"] == "clinician":
        out |= {k: item.get(k) for k in ("anchor", "traits", "confounders", "why")}
    else:
        out["needs"] = item.get("needs")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--allow", nargs="*", default=[], help="items whose check problems are accepted"
    )
    args = ap.parse_args()
    dsn = os.environ["DATABASE_URL"]
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    vignettes = load_vignettes()
    try:
        items = questions_stage(vignettes, set(args.allow))
        pools = pool_stage(items, vignettes, dsn, base_url)
        labels = oracle_stage(items, pools, dsn)
    except AwaitingResponse as e:
        print(f"awaiting: {e}")
        sys.exit(2)
    fixture = [fixture_item(i, pools[i["id"]], labels[i["id"]]) for i in items]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "queries.json").write_text(
        json.dumps({"items": fixture}, indent=1, ensure_ascii=False) + "\n"
    )
    counts = {k: sum(i["kind"] == k for i in fixture) for k in KIND_PREFIX}
    manifest = {
        "what": "final-evaluation items on chips_scale: clinician questions, new patient texts, out-of-scope questions, with oracle units grouped into key points",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "schema": SCHEMA,
        "scale_answers_digest": chips_fixture.digest(),
        "prompts": ["final_eval_questions.v1", "final_eval_oracle.v1"],
        "author": "Claude Sonnet (Claude Code subagent)",
        "labeller": "Claude Sonnet (Claude Code subagent)",
        "pool": {
            "searches": list(SEARCHES),
            "grouping": [False, True],
            "k": POOL_K,
            "design_cap": DESIGN_CAP,
            "cap": POOL_CAP,
        },
        "counts": counts,
        "answerable": {a: sum(i["answerable"] == a for i in fixture) for a in sorted(ANSWERABLE)},
        "key_points": sum(len(i["key_points"]) for i in fixture),
        "allowed_problems": sorted(args.allow),
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
