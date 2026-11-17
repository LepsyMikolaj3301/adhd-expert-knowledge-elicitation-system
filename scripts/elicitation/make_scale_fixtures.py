# ruff: noqa: E501  (persona and scenario strings)
"""A larger local chip fixture: 20 experts, 24 vignettes, to see retrieval with many experts per vignette.

Usage:
    python scripts/elicitation/make_scale_fixtures.py --stage seed
        # copy V001-V014 and the two silver documents (experts 1-2) into the scale folder
    python scripts/elicitation/make_scale_fixtures.py --stage vignettes
        # 10 new vignettes (V015-V024): inbox requests for Claude Code subagents, as for the silver ones
    python scripts/elicitation/make_scale_fixtures.py --stage answers [--model qwen3.8:27b]
        # 18 more experts (3-20) answer through a local model; resumable (data/cache)
    python scripts/elicitation/make_scale_fixtures.py --stage answers --check --experts 3 4 --vignettes V001
        # try some (expert, vignette) pairs, print them, write nothing
    python scripts/elicitation/make_scale_fixtures.py --stage build [--classifier qwen3.5:9b] [--schema chips_scale]
        # classify the sentences, build and embed the units, load them into Postgres

Everything lives under the gitignored data/: fixtures in data/fixtures_chips_scale/synthetic/silver,
units in data/expert_units_chips_scale/synthetic/silver/<tag>, rows in the Postgres schema
`chips_scale`. Nothing here touches tests/fixtures, the schemas `chips` and `chips_silver`, or the
files of make_chip_fixtures.py (its functions are imported).

Who answers what: V001, V004, V006, V012 ("anchors") are answered by all 20 experts; each of the other
20 vignettes by the experts that rotate over them (the old vignettes by the 2 silver experts as well).
So a vignette has 3 to 20 experts. Experts 3-20 are written by the local model, in three of the four
answer kinds (the local model never sets insufficient_information when told to). Their wording is
more alike than real clinicians'; the number of experts per vignette is what this fixture is for.
"""

import argparse
import json
import os
import shutil
import sys
from datetime import timedelta
from functools import partial
from pathlib import Path

import make_chip_fixtures as mcf
from chips_schema import ChipDocument, ChipResponse
from elicitation_schema import Vignette, content_hash
from llm_clients import CachedGenerator, InboxGenerator, OllamaGenerator
from make_fixtures import (
    EPOCH,
    PERSONAS,
    Gen,
    check_text,
    design_from_output,
    fixture_dir,
    parse_json,
    write_json,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/fixtures_chips_scale"
UNITS = ROOT / "data/expert_units_chips_scale/synthetic"
SOURCE = ROOT / "data/fixtures_chips"
TIER = "silver"  # the tooling knows two tiers; the manifest says who wrote the answers
SCHEMA = "chips_scale"
ANCHORS = ["V001", "V004", "V006", "V012"]
OLD_VIGNETTES = [f"V{i:03d}" for i in range(1, 15)]
NEW_FIRST = 15
KINDS = mcf.KINDS[:3]  # the local model rejects insufficient_info every time

NO_TRAITS = "none: this person has no notable attention or organisation difficulties"

# V015-V024: written by Claude subagents from these scenarios (same prompt as the silver vignettes)
SCENARIOS = [
    dict(
        id="N01",
        age=27,
        topic="handover notes after a run of night shifts",
        source="personal_journal",
        situation="junior doctor on a rotating rota, lives alone",
        style="clipped, lists, drifts into complaints about the rota",
        traits="sustained_attention_on_boring_tasks: moderate; working_memory: weak",
        confounders="three weeks of night shifts and very little sleep",
        max_cues=2,
        control=False,
    ),
    dict(
        id="N02",
        age=52,
        topic="missed appointments and lost words lately",
        source="email",
        situation="part-time librarian, two grown-up children",
        style="polite, apologetic, long explanatory sentences",
        traits="working_memory: moderate; distractibility: weak",
        confounders="perimenopause symptoms and worry about her mother's illness",
        max_cues=2,
        control=False,
    ),
    dict(
        id="N03",
        age=38,
        topic="a woodworking project while the washing piles up",
        source="forum_post",
        situation="stay-at-home parent of a toddler",
        style="chatty, enthusiastic, many asides in brackets",
        traits="sustained_attention_on_boring_tasks: strong; novelty_seeking: moderate",
        confounders="a toddler who wakes at night",
        max_cues=2,
        control=False,
    ),
    dict(
        id="N04",
        age=31,
        topic="planning a week in Portugal with friends",
        source="email",
        situation="accountant, shares a house",
        style="organised, bullet-like, practical",
        traits=NO_TRAITS,
        confounders="none",
        max_cues=0,
        control=True,
    ),
    dict(
        id="N05",
        age=22,
        topic="not starting exam revision",
        source="personal_journal",
        situation="third-year chemistry student",
        style="self-critical, short bursts, lists of plans never carried out",
        traits="task_initiation: strong; distractibility: moderate",
        confounders="strong exam anxiety and a recent break-up",
        max_cues=3,
        control=False,
    ),
    dict(
        id="N06",
        age=47,
        topic="a noisy neighbour and the council",
        source="forum_post",
        situation="bus driver, lives alone",
        style="blunt, annoyed, numbered grievances",
        traits=NO_TRAITS,
        confounders="irritation and poor sleep because of the noise",
        max_cues=0,
        control=True,
    ),
    dict(
        id="N07",
        age=36,
        topic="an overdue project update for the team",
        source="email",
        situation="software tester writing to a colleague",
        style="rambling with nested clauses, returns to the point late",
        traits="discourse_tangentiality: moderate; time_estimation: weak",
        confounders="anxious about being judged by a new manager",
        max_cues=2,
        control=False,
        track="text_analysis",
        trait_key="discourse_tangentiality",
        knowledge_target="Telling digression that resolves from anxious over-explaining in a work email (textual markers, not diagnostic criteria).",
    ),
    dict(
        id="N08",
        age=29,
        topic="a spending spree and the bank account afterwards",
        source="forum_post",
        situation="sales assistant, renting a room",
        style="fast, impulsive phrasing, exclamation marks, then regret",
        traits="quick_to_act: moderate; emotional_reactivity: weak",
        confounders="a low mood that started after a bad winter",
        max_cues=2,
        control=False,
        track="text_analysis",
        trait_key="quick_to_act",
        knowledge_target="Reading impulsive action and regret language in free text versus mood-driven spending.",
    ),
    dict(
        id="N09",
        age=55,
        topic="what school was like and why it comes back now",
        source="personal_journal",
        situation="recently retired teacher",
        style="reflective, slow, long paragraphs",
        traits="distractibility: moderate, recalled from childhood; task_initiation: moderate",
        confounders="low mood after retiring and a recent bereavement",
        max_cues=2,
        control=False,
        track="text_analysis",
        trait_key="retrospective_childhood",
        knowledge_target="Weighing a retrospective account of childhood attention in an older adult's free text.",
    ),
    dict(
        id="N10",
        age=40,
        topic="a weekend in the allotment",
        source="personal_journal",
        situation="warehouse supervisor, married",
        style="plain, past tense, short sentences",
        traits=NO_TRAITS,
        confounders="a low mood since the winter",
        max_cues=0,
        control=True,
    ),
]

# Experts 3-20 (E03...E20). Role, years, writing style and how strictly they read a text.
_PERSONAS = [
    (
        "E03",
        "consultant psychiatrist, 22 years in a university ADHD clinic; careful, cautious reader who rarely rates above 3; full plain sentences, cites the differential first",
    ),
    (
        "E04",
        "GP with a special interest in adult neurodevelopment, 12 years; practical, blunt, short sentences, thinks about what can be done in a ten-minute consultation",
    ),
    (
        "E05",
        "clinical psychologist, 6 years in an NHS adult ADHD pathway; reads generously, over-reads weak cues, hedges afterwards; medium-length answers",
    ),
    (
        "E06",
        "neuropsychologist, 14 years, research background; precise, mentions base rates and measurement error, writes long structured answers",
    ),
    (
        "E07",
        "ADHD specialist nurse, 10 years; patient-centred, notes what the person says about daily life, short clear sentences, little jargon",
    ),
    (
        "E08",
        "psychiatry registrar in training, 3 years; eager, unsure, many 'I think', asks what a senior would say, answers of uneven length",
    ),
    (
        "E09",
        "occupational therapist in a mental health team, 16 years; reads text for function (work, home), practical, cross-refers to routines",
    ),
    (
        "E10",
        "consultant psychiatrist, 9 years, mainly mood disorders; sceptical about ADHD, looks for depression and anxiety first, terse shorthand",
    ),
    (
        "E11",
        "clinical psychologist, 20 years, private practice; reflective, narrative style, long answers with examples from other patients (never names)",
    ),
    (
        "E12",
        "general adult psychiatrist, 5 years; base-rate minded, says what is common before what is rare, medium answers with a clear structure",
    ),
    (
        "E13",
        "psychotherapist and counsellor, 11 years; reads emotion and relationships in the text, less on cognition, warm plain sentences",
    ),
    (
        "E14",
        "paediatrician moving into adult services, 8 years; compares with childhood presentations, careful with retrospective accounts",
    ),
    (
        "E15",
        "research psychologist with a clinic day a week, 7 years; quotes the text exactly, flags what cannot be concluded, formal, hedged",
    ),
    (
        "E16",
        "community psychiatric nurse, 18 years; pragmatic, cares about risk and sleep, short sentences, abbreviations",
    ),
    (
        "E17",
        "consultant psychiatrist, 25 years; reads quickly, trusts gestalt, writes one line for some answers and a paragraph for others",
    ),
    (
        "E18",
        "clinical psychologist, 4 years; thorough, lists alternative explanations one by one, long answers, asks for more information often",
    ),
    (
        "E19",
        "GP trainee, 2 years; cautious, safety-first, unsure, short answers that name what to ask the patient next",
    ),
    (
        "E20",
        "neurodevelopmental assessor, 13 years, trained in autism and ADHD; looks at how the text is written (structure, tangents), plain but long",
    ),
]
HABITS = list(mcf.CHIP_HABITS.values())
for _i, (_pid, _) in enumerate(_PERSONAS):
    mcf.CHIP_HABITS.setdefault(_pid, HABITS[_i % len(HABITS)])
ALL_PERSONAS = list(PERSONAS["silver"]) + _PERSONAS  # index = document number - 1 (role_for)


def with_scale_personas() -> None:
    """Experts 3-20 in make_fixtures.PERSONAS['silver'], where role_for looks them up by session number."""
    names = {p for p, _ in PERSONAS["silver"]}
    PERSONAS["silver"].extend(p for p in _PERSONAS if p[0] not in names)


# --- the rotation ----------------------------------------------------------------------------


def background(vignettes: list[str]) -> list[str]:
    return [v for v in vignettes if v not in ANCHORS]


def rotation(expert: int, vignettes: list[str], seed: int) -> list[str]:
    """Vignettes expert `expert` (3-20) answers: the anchors plus 4 or 5 of the others, taken in turn
    so that every vignette gets about the same number of experts."""
    others = background(vignettes)
    idx = expert - 3
    take = 5 if idx % 2 == 0 else 4
    start = (sum(5 if i % 2 == 0 else 4 for i in range(idx)) + seed * 7) % len(others)
    picked = [others[(start + j) % len(others)] for j in range(take)]
    return sorted(set(ANCHORS) | set(picked))


def kind_for(expert: int, position: int, seed: int) -> str:
    return KINDS[(expert + position + seed) % len(KINDS)]


# --- stages ----------------------------------------------------------------------------------


def seed_stage(out: Path) -> None:
    src = fixture_dir(TIER, "synthetic", SOURCE)
    dst = fixture_dir(TIER, "synthetic", out)
    for folder in ("vignettes", "documents", "claims"):
        (dst / folder).mkdir(parents=True, exist_ok=True)
    for p in sorted((src / "vignettes").glob("V*.json")):
        shutil.copy2(p, dst / "vignettes" / p.name)
    for n in (1, 2):
        shutil.copy2(src / "documents" / f"DOC-SYN-{n:04d}.json", dst / "documents")
        shutil.copy2(src / "claims" / f"DOC-SYN-{n:04d}.claims.json", dst / "claims")
    manifest = json.loads((src / "manifest.json").read_text())
    manifest["quality"] = (
        "scale fixture: experts 1-2 are the silver documents (Claude subagents); experts 3-20 are "
        "written by a local model; V001-V014 as in silver, V015-V024 by Claude subagents. Not "
        "expert-reviewed: for how retrieval behaves with many experts, not for quality numbers"
    )
    write_json(dst / "manifest.json", manifest)
    print(f"seeded {dst}: 14 vignettes, 2 documents")


def vignettes_stage(gen: Gen, inbox: Path, out: Path, only: list[str] | None) -> int:
    dst = fixture_dir(TIER, "synthetic", out)
    done = 0
    for n, sc in enumerate(SCENARIOS):
        vid = f"V{NEW_FIRST + n:03d}"
        if only and sc["id"] not in only:
            continue
        if (dst / "vignettes" / f"{vid}.json").exists():
            done += 1
            continue

        def build(raw, sc=sc):
            data = parse_json(raw)
            text = str(data.get("text", "")).strip()
            check_text(text)
            return text, design_from_output(data, sc, text)

        got = mcf.attempt(gen, mcf.persona_request(sc), build, inbox)
        if got is None:
            continue
        text, design = got
        v = Vignette(
            id=vid, version=1, text=text, content_hash=content_hash(text), framing=sc["source"],
            design=design, question_ids=list(mcf.CHIP_QUESTIONS), variant=None,
        )  # fmt: skip
        write_json(dst / "vignettes" / f"{vid}.json", v.model_dump(mode="json"))
        done += 1
        print(f"{vid} written ({len(text.split())} words)")
    want = len([s for s in SCENARIOS if not only or s["id"] in only])
    print(f"{done}/{want} new vignettes ready")
    return 0 if done >= want else 1


def load_vignettes(out: Path) -> dict[str, Vignette]:
    folder = fixture_dir(TIER, "synthetic", out) / "vignettes"
    return {
        p.stem: Vignette.model_validate_json(p.read_text()) for p in sorted(folder.glob("V*.json"))
    }


def answer_one(gen: Gen, v: Vignette, kind: str, expert: int, inbox: Path, skipped: list[str]):
    pid, persona = ALL_PERSONAS[expert - 1]
    req = mcf.answer_request(v, kind, pid, persona)  # key answer:<vignette>:<kind>:<E03>
    got = mcf.attempt(
        gen, req,
        lambda raw: mcf.chip_answer_pieces(parse_json(raw), v, kind, mcf.forbidden_for(v)),
        inbox,
    )  # fmt: skip
    if got is None:
        skipped.append(req.key)
    return got


def answers_stage(args: argparse.Namespace, log: list, accepted: dict, attempts: dict) -> int:
    vignettes = load_vignettes(args.out)
    if len(vignettes) < 24 and not args.vignettes:
        print(f"{len(vignettes)}/24 vignettes: run --stage vignettes first", file=sys.stderr)
        return 1
    generator = CachedGenerator(OllamaGenerator(args.base_url, args.model), args.cache)
    gen = Gen("ollama", generator, args.retries, args.seed, log, accepted, attempts)
    dst = fixture_dir(TIER, "synthetic", args.out)
    experts = args.experts or list(range(3, 21))
    skipped: list[str] = []
    for expert in experts:
        session_id, expert_id = f"DOC-SYN-{expert:04d}", f"SYN-{expert:03d}"
        path = dst / "documents" / f"{session_id}.json"
        if path.exists() and not args.check:
            continue
        mine = rotation(expert, sorted(vignettes), args.seed)
        if args.vignettes:
            mine = [v for v in mine if v in args.vignettes]
        day, clock = EPOCH + timedelta(days=expert - 1), EPOCH + timedelta(days=expert - 1)
        responses, claims_out, shown = [], [], []
        for position, vid in enumerate(mine):
            v = vignettes[vid]
            got = answer_one(
                gen, v, kind_for(expert, position, args.seed), expert, args.inbox, skipped
            )
            if got is None:
                continue
            answers, highlights, rating, insufficient, claims = got
            started = clock + timedelta(minutes=1)
            clock = started + timedelta(minutes=4 + len(answers["Q1"]) // 80)
            responses.append(ChipResponse(
                vignette_id=v.id, vignette_version=v.version, vignette_hash=v.content_hash,
                expert_id=expert_id, is_synthetic=True, answers=answers, highlights=highlights,
                rating=rating, insufficient_information=insufficient, started_at=started,
                submitted_at=clock,
            ))  # fmt: skip
            claims_out += claims
            shown.append(v)
            if args.check:
                print(
                    f"{expert_id} {vid}: {len(highlights)} highlights, rating {rating}, {len(claims)} claims"
                )
                print("  Q1:", answers["Q1"][:300].replace("\n", " "))
        if args.check or not responses:
            continue
        if len(responses) < len(mine):
            print(
                f"{session_id}: {len(responses)}/{len(mine)} answers, not written", file=sys.stderr
            )
            continue
        doc = ChipDocument(
            session_id=session_id, expert_id=expert_id, created_at=day, is_synthetic=True,
            vignettes=shown, responses=responses,
        )  # fmt: skip
        write_json(path, doc.model_dump(mode="json"))
        write_json(
            dst / "claims" / f"{session_id}.claims.json", [c.model_dump() for c in claims_out]
        )
        print(f"{session_id}: {len(responses)} answers ({', '.join(mine)})")
    if skipped:
        print(
            f"{len(skipped)} answers missing:\n  " + "\n  ".join(sorted(skipped)), file=sys.stderr
        )
        return 1
    if not args.check:
        manifest_path = dst / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["answers_by"] = (
            f"experts 3-20: ollama:{args.model}, kinds {KINDS}, seed {args.seed}"
        )
        manifest["rotation"] = {
            str(e): rotation(e, sorted(vignettes), args.seed) for e in range(3, 21)
        }
        write_json(manifest_path, manifest)
    return 0


def seed_schema(args: argparse.Namespace, classifier: str, dsn: str) -> None:
    """Freeze the built units into a scratch snapshot under data/ and seed `args.schema` from it.

    Same route as the silver schema: one session per (document, vignette) with a findings record,
    which is what the retrievers read their patient words from. load_chips_pg stores the raw
    document instead, so retrieval would run without them.
    """
    sys.path.insert(0, str(ROOT / "scripts" / "db"))
    sys.path.insert(0, str(ROOT / "scripts" / "rag"))
    import chip_retrieval
    import chips_snapshot
    import classify_sentence_targets
    import psycopg
    from psycopg import sql

    snapshot = args.units.parent / f"{args.units.name}_snapshot"
    chips_snapshot.SNAPSHOT = snapshot  # freeze writes here, not into tests/fixtures
    classify_sentence_targets.UNITS = args.units
    chip_retrieval.load_chip_fixture = partial(chip_retrieval.load_chip_fixture, fixtures=args.out)
    if code := chips_snapshot.freeze(argparse.Namespace(tier=TIER, classifier=classifier)):
        raise SystemExit(code)
    with psycopg.connect(dsn, autocommit=True) as conn:
        # The drop is in the transaction too: a failed seed leaves the old schema as it was.
        conn.execute("BEGIN")
        try:
            conn.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(args.schema))
            )
            counts = chips_snapshot.seed(conn, args.schema, snapshot)
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    print(f"seeded {args.schema}: {counts}")


def build_stage(args: argparse.Namespace) -> int:
    """classify -> build units + embed -> freeze and seed Postgres, with the scale roots and personas."""
    sys.path.insert(0, str(ROOT / "scripts" / "db"))
    import build_chip_units
    import classify_sentence_targets
    import psycopg

    from app.settings import settings

    # Before the long classify and embed steps, not after them.
    dsn = settings.database_url
    try:
        psycopg.connect(dsn, connect_timeout=5).close()
    except psycopg.OperationalError as exc:
        raise SystemExit(f"Postgres is not reachable ({exc}); start it first") from exc

    with_scale_personas()
    common = ["--tier", TIER, "--fixtures", str(args.out), "--out", str(args.units)]
    tag = classify_sentence_targets.model_tag(args.classifier)
    steps = [
        (classify_sentence_targets.main, ["--model", args.classifier, *common]),
        (build_chip_units.main, ["--classifier", args.classifier, *common]),
    ]
    if not args.skip_units:
        for main, argv in steps:
            print(f"== {main.__module__} {' '.join(argv)}")
            if code := main(argv):
                return code
    seed_schema(args, args.classifier, dsn)
    print(f"built {args.units / TIER / tag}; seeded schema {args.schema}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stage", choices=["seed", "vignettes", "answers", "build"], required=True)
    ap.add_argument("--model", default="qwen3.8:27b", help="answers stage: writes experts 3-20")
    ap.add_argument("--classifier", default="qwen3.5:9b", help="build stage")
    ap.add_argument("--schema", default=SCHEMA, help="build stage: Postgres schema to (re)load")
    ap.add_argument(
        "--base-url", default=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    ap.add_argument("--inbox", type=Path, default=ROOT / "data/inbox")
    ap.add_argument("--cache", type=Path, default=ROOT / "data/cache")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--units", type=Path, default=UNITS)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument(
        "--skip-units", action="store_true", help="build stage: units exist, only freeze and seed"
    )
    ap.add_argument("--experts", type=int, nargs="+", help="answers: only these experts (3-20)")
    ap.add_argument("--vignettes", nargs="+", help="answers: only these vignettes")
    ap.add_argument("--only", nargs="+", help="vignettes stage: only these scenario ids (N01 ...)")
    ap.add_argument(
        "--check", action="store_true", help="answers: print the answers, write nothing"
    )
    args = ap.parse_args(argv)
    if args.schema in ("chips", "chips_silver", "chips_eval"):
        raise SystemExit(f"--schema {args.schema} is not for the scale fixture")

    log: list[str] = []
    accepted: dict[str, str] = {}
    attempts: dict[str, int] = {}
    if args.stage == "seed":
        seed_stage(args.out)
        return 0
    if args.stage == "vignettes":
        gen = Gen("claude", InboxGenerator(args.inbox), 0, args.seed, log, accepted, attempts)
        code = vignettes_stage(gen, args.inbox, args.out, args.only)
        if code:
            print("waiting:\n  " + "\n  ".join(log))
        return code
    if args.stage == "answers":
        return answers_stage(args, log, accepted, attempts)
    return build_stage(args)


if __name__ == "__main__":
    sys.exit(main())
