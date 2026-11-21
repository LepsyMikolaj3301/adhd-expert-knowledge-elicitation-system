# ruff: noqa: E501  (persona and scenario strings)
"""A larger local chip fixture: 32 experts, 24 vignettes, to see retrieval with many experts per vignette.

Usage:
    python scripts/elicitation/make_scale_fixtures.py --stage seed
        # copy V001-V014 and the two silver documents (experts 1-2) into the scale folder
    python scripts/elicitation/make_scale_fixtures.py --stage vignettes
        # 10 new vignettes (V015-V024): inbox requests for Claude Code subagents, as for the silver ones
    python scripts/elicitation/make_scale_fixtures.py --stage answers [--model qwen3.8:27b]
        # experts 3-20 answer through --model, experts 21-32 through the model of their persona file
        # (prompts/expert_personas/E21.v1.md ...: gpt-oss, mistral-small, qwen); resumable (data/cache)
    python scripts/elicitation/make_scale_fixtures.py --stage answers --check --experts 3 21 --vignettes V001
        # try some (expert, vignette) pairs, print them, write nothing
    python scripts/elicitation/make_scale_fixtures.py --stage proofread [--proofread-out DIR]
        # every answer through the web application's proofreading (garbage, grammar, fuller
        # sentences, grammar, one sentence per line) into a second fixture folder; needs LanguageTool
        # and Ollama; resumable per (document, vignette)
    python scripts/elicitation/make_scale_fixtures.py --stage build [--proofread] [--classifier qwen3.5:9b]
        # classify the sentences, build and embed the units, load them into Postgres: the raw answers
        # into the schema chips_scale_raw, with --proofread the proofread ones into chips_scale; with
        # --proofread it also rewrites the test fixture tests/fixtures/scale_answers (answers + labels)

Everything lives under the gitignored data/: fixtures in data/fixtures_chips_scale/synthetic/silver
(proofread: data/fixtures_chips_scale_proofread), units in data/expert_units_chips_scale/synthetic/
silver/<tag> (proofread: data/expert_units_chips_scale_proofread), rows in the Postgres schemas
`chips_scale` and `chips_scale_raw`. Only `build --proofread` writes to tests/fixtures (scale_answers); nothing here
touches the schemas `chips` and `chips_silver`, or the
files of make_chip_fixtures.py (its functions are imported).

Who answers what: V001, V004, V006, V012 ("anchors") are answered by all 20 experts; each of the other
20 vignettes by the experts that rotate over them (the old vignettes by the 2 silver experts as well).
So a vignette has 3 to 32 experts. Experts 3-20 are written by one local model from one-line
personas, in three of the four answer kinds (the local model never sets insufficient_information when
told to); their wording is more alike than real clinicians'. Experts 21-32 differ on purpose: each has
a persona file (its own system prompt and way of writing and citing) and a model of its own, and is
asked through Synthetic_expert_answer.v5, with no shared style rotation.
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import timedelta
from difflib import SequenceMatcher
from functools import partial
from pathlib import Path

import make_chip_fixtures as mcf
from chips_schema import ChipDocument, ChipResponse
from elicitation_schema import Vignette, content_hash
from llm_clients import CachedGenerator, GenRequest, InboxGenerator, OllamaGenerator
from make_fixtures import (
    ANSWER_OPTIONS,
    EPOCH,
    PERSONAS,
    Gen,
    check_text,
    design_from_output,
    fixture_dir,
    parse_json,
    write_json,
)
from prompt_loader import load_prompt

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/fixtures_chips_scale"
UNITS = ROOT / "data/expert_units_chips_scale/synthetic"
SOURCE = ROOT / "data/fixtures_chips"
TIER = "silver"  # the tooling knows two tiers; the manifest says who wrote the answers
SCHEMA = "chips_scale_raw"  # the raw answers; the proofread ones go to chips_scale
PROOFREAD_SCHEMA = "chips_scale"
ANCHORS = ["V001", "V004", "V006", "V012"]
OLD_VIGNETTES = [f"V{i:03d}" for i in range(1, 15)]
NEW_FIRST = 15
KINDS = mcf.KINDS[:3]  # the local model rejects insufficient_info every time
PERSONA_EXPERTS = list(range(21, 33))  # their own persona file, model and prompt (answer v5)
ANSWER_V5 = "Synthetic_expert_answer.v5"
LAST_EXPERT = 32
PROOFREAD_OUT = ROOT / "data/fixtures_chips_scale_proofread"
PROOFREAD_UNITS = ROOT / "data/expert_units_chips_scale_proofread/synthetic"

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


def load_persona(expert: int):
    """The persona file of expert 21-32: front-matter (role, model, think, citation), `system` is
    the expert's own system prompt, `user` their way of writing."""
    return load_prompt(f"expert_personas/E{expert:02d}.v1")


# (id, "role, years; how they write"): the role_for line is the first two comma parts of this
_FILE_PERSONAS = [
    (f"E{n}", f"{load_persona(n).meta['role']}; {load_persona(n).meta['citation']}")
    for n in PERSONA_EXPERTS
]
ALL_PERSONAS = list(PERSONAS["silver"]) + _PERSONAS + _FILE_PERSONAS  # index = document number - 1


def with_scale_personas() -> None:
    """Experts 3-32 in make_fixtures.PERSONAS['silver'], where role_for looks them up by session number."""
    names = {p for p, _ in PERSONAS["silver"]}
    PERSONAS["silver"].extend(p for p in _PERSONAS + _FILE_PERSONAS if p[0] not in names)


# --- the rotation ----------------------------------------------------------------------------


def background(vignettes: list[str]) -> list[str]:
    return [v for v in vignettes if v not in ANCHORS]


def rotation(expert: int, vignettes: list[str], seed: int) -> list[str]:
    """Vignettes expert `expert` (3-32) answers: the anchors plus 4 or 5 of the others, taken in turn
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


CLAIM_DIRECTION = {"toward": "raises", "away": "lowers", "unclear": "neutral"}
QUOTE_MARKS = "\"'\u201c\u201d\u2018\u2019 \t.,;:"
APOSTROPHES = {"'": "\u2019", "\u2019": "'"}


def nearest_span(text: str, vignette: str, floor: float = 0.9) -> str | None:
    """The stretch of the vignette (whole words) most like `text`, if it is very like it: a copy
    that lost a contraction ("I'd" -> "I") or a comma, not a different sentence."""
    words = [(m.start(), m.end()) for m in re.finditer(r"\S+", vignette)]
    want = text.lower().split()
    best, best_ratio = None, floor
    for size in range(max(len(want) - 2, 1), len(want) + 3):
        for i in range(len(words) - size + 1):
            a, b = words[i][0], words[i + size - 1][1]
            ratio = SequenceMatcher(None, text.lower(), vignette[a:b].lower()).ratio()
            if ratio > best_ratio:
                best, best_ratio = vignette[a:b], ratio
    return best.strip(QUOTE_MARKS) if best else None


def mend_highlight(text: str, vignette: str) -> str:
    """A highlight copied with the quotation marks around it, with the other kind of apostrophe, or
    with a small slip (a lost contraction), as the text it was copied from. Anything else comes back
    unchanged (and is then rejected)."""
    if text in vignette:
        return text
    for candidate in (text.strip(QUOTE_MARKS), text.strip()):
        swapped = "".join(APOSTROPHES.get(c, c) for c in candidate)
        for option in (candidate, swapped):
            if option and option in vignette:
                return option
    return nearest_span(text.strip(QUOTE_MARKS), vignette) or text


def repair(data: dict, vignette: str = "") -> dict:
    """Slips of the persona models that leave the answer as it is, mended before the checks:
    the string "null" for an empty quote, a highlight's direction word on a claim, a claim about
    Q6 (the rating, not an open answer), quotation marks or apostrophes in a copied highlight.
    A highlight that is not in the text is never invented."""
    highlights = data.get("highlights")
    if vignette and isinstance(highlights, list):
        data = {
            **data,
            "highlights": [
                {**h, "text": mend_highlight(h["text"], vignette)}
                if isinstance(h, dict) and isinstance(h.get("text"), str)
                else h
                for h in highlights
            ],
        }
    claims = data.get("gold_claims")
    if not isinstance(claims, list):
        return data
    mended = []
    for claim in claims:
        if isinstance(claim, dict):
            if claim.get("question_id") not in mcf.OPEN_QUESTIONS:
                continue
            claim = dict(claim)
            span = str(claim.get("quoted_span_text") or "").strip()
            if span.lower() in ("", "null", "none"):
                claim["quoted_span_text"] = None
            elif vignette:
                claim["quoted_span_text"] = mend_highlight(span, vignette)
            claim["direction"] = CLAIM_DIRECTION.get(claim.get("direction"), claim.get("direction"))
        mended.append(claim)
    return {**data, "gold_claims": mended}


def persona_request(v: Vignette, expert: int) -> tuple[GenRequest, str, str | bool]:
    """Answer v5 for experts 21-32: their system prompt, their way of writing. -> (request, model, think)."""
    persona = load_persona(expert)
    think = persona.meta["think"]
    think = False if think in ("none", "false") else think
    p = load_prompt(ANSWER_V5).fill(
        PERSONA_SYSTEM=persona.system, WRITING_STYLE=persona.user, FRAMING=v.framing,
        VIGNETTE_TEXT=v.text, QUESTIONS=mcf.questions_text(v),
    )  # fmt: skip
    options = dict(ANSWER_OPTIONS)
    if "repeat_penalty" in persona.meta:  # a persona whose model falls into repetition loops
        options["repeat_penalty"] = float(persona.meta["repeat_penalty"])
    if think:  # a thinking model spends part of the budget before the JSON starts
        options["num_predict"] = 6000
    req = GenRequest(
        key=f"answer:{v.id}:persona:E{expert:02d}", system=p.system, user=p.user, json_mode=True,
        options=options,
    )  # fmt: skip
    return req, persona.meta["model"], think


def answer_one(gen_for, v: Vignette, kind: str, expert: int, inbox: Path, skipped: list[str]):
    """`gen_for(model, think)` is the Gen of a model. Experts 3-20: the shared model, shared prompt
    (v4, a style kind from the rotation); 21-32: their persona file and model (v5)."""
    if expert in PERSONA_EXPERTS:
        req, model, think = persona_request(v, expert)
        gen = gen_for(model, think)
        kind = "clean"  # v5 has no style kinds: the persona is the style
    else:
        pid, persona = ALL_PERSONAS[expert - 1]
        req = mcf.answer_request(v, kind, pid, persona)  # key answer:<vignette>:<kind>:<E03>
        gen = gen_for(None, False)
    fix = partial(repair, vignette=v.text) if expert in PERSONA_EXPERTS else (lambda data: data)
    got = mcf.attempt(
        gen, req,
        lambda raw: mcf.chip_answer_pieces(fix(parse_json(raw)), v, kind, mcf.forbidden_for(v)),
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
    gens: dict[str, Gen] = {}

    def gen_for(model: str | None, think) -> Gen:
        model = model or args.model
        if model not in gens:
            inner = OllamaGenerator(args.base_url, model, think=think)
            gens[model] = Gen(
                "ollama", CachedGenerator(inner, args.cache), args.retries, args.seed, log,
                accepted, attempts,
            )  # fmt: skip
        return gens[model]

    dst = fixture_dir(TIER, "synthetic", args.out)
    experts = args.experts or list(range(3, LAST_EXPERT + 1))
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
                gen_for, v, kind_for(expert, position, args.seed), expert, args.inbox, skipped
            )
            if got is None:
                continue
            answers, highlights, rating, insufficient, claims = got
            started = clock + timedelta(minutes=1)
            clock = started + timedelta(minutes=4 + len(answers["Q1"]) // 80)
            responses.append(ChipResponse(
                vignette_id=v.id, vignette_version=v.version, vignette_hash=v.content_hash,
                expert_id=expert_id, answers=answers, highlights=highlights,
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
            session_id=session_id, expert_id=expert_id, created_at=day,
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
            f"experts 3-20: ollama:{args.model}, kinds {KINDS}, seed {args.seed}; experts 21-32: "
            f"their persona file and model ({ANSWER_V5}), seed {args.seed}"
        )
        manifest["answer_models"] = {
            f"SYN-{e:03d}": load_persona(e).meta["model"] if e in PERSONA_EXPERTS else args.model
            for e in range(3, LAST_EXPERT + 1)
        }
        manifest["rotation"] = {
            str(e): rotation(e, sorted(vignettes), args.seed) for e in range(3, LAST_EXPERT + 1)
        }
        write_json(manifest_path, manifest)
    return 0


def preflight_proofread() -> None:
    """The proofreading is the web application's own pipeline; without its services an answer would
    be filed unchecked (the pipeline skips an unreachable pass), so refuse to start."""
    import httpx

    from app.settings import settings

    for name, url in (
        ("LanguageTool", f"{settings.languagetool_url}/v2/languages"),
        ("Ollama", f"{settings.ollama_base_url}/api/tags"),
    ):
        try:
            httpx.get(url, timeout=10).raise_for_status()
        except httpx.HTTPError as exc:
            raise SystemExit(f"{name} is not reachable at {url} ({exc}); start it first") from exc
    settings.require_compute = True  # an unreachable service now fails the answer, never skips it


async def proofread_response(resp: ChipResponse, vignette: Vignette) -> dict[str, dict]:
    """The answers of one response through proofread_answer, as app.proofread.service.prepare does."""
    from app.proofread.pipeline import proofread_answer
    from app.vignettes.questions import QUESTIONS, render_question

    quotes = {h.chip: h.text for h in resp.highlights}
    rows = {}
    for qid, answer in resp.answers.items():
        result = await proofread_answer(
            render_question(QUESTIONS[qid], None), answer, quotes, vignette.text
        )
        rows[qid] = {
            "original": answer, "proposed": result.text, "dropped": result.dropped,
            "passes": result.passes,
        }  # fmt: skip
    return rows


def proofread_stage(args: argparse.Namespace) -> int:
    """Every document of --out through the proofreading, into --proofread-out (resumable)."""
    import asyncio

    from app.assignments.answers import CHIP_RE

    preflight_proofread()
    src = fixture_dir(TIER, "synthetic", args.out)
    dst = fixture_dir(TIER, "synthetic", args.proofread_out)
    for folder in ("vignettes", "documents", "claims", "proofread"):
        (dst / folder).mkdir(parents=True, exist_ok=True)
    for folder in ("vignettes", "claims"):
        for path in (src / folder).glob("*.json"):
            shutil.copy2(path, dst / folder / path.name)
    versions: set[str] = set()
    for path in sorted((src / "documents").glob("DOC-*.json")):
        if (dst / "documents" / path.name).exists():
            continue
        doc = ChipDocument.model_validate_json(path.read_text())
        side_path = dst / "proofread" / f"{doc.session_id}.json"
        side = json.loads(side_path.read_text()) if side_path.exists() else {}
        responses = []
        for resp in doc.responses:
            if resp.vignette_id not in side:
                vignette = next(v for v in doc.vignettes if v.id == resp.vignette_id)
                side[resp.vignette_id] = asyncio.run(proofread_response(resp, vignette))
                write_json(side_path, side)  # resume per (document, vignette)
            rows = side[resp.vignette_id]
            for qid, row in rows.items():
                if sorted(CHIP_RE.findall(row["original"])) != sorted(
                    CHIP_RE.findall(row["proposed"])
                ):
                    raise SystemExit(f"{doc.session_id} {resp.vignette_id} {qid}: chips changed")
                if not row["proposed"].strip():
                    raise SystemExit(f"{doc.session_id} {resp.vignette_id} {qid}: answer is empty")
                if v := row["passes"].get("languagetool"):
                    versions.add(str(v))
            answers = {qid: rows[qid]["proposed"] for qid in resp.answers}
            responses.append(resp.model_copy(update={"answers": answers}))
        write_json(
            dst / "documents" / path.name,
            doc.model_copy(update={"responses": responses}).model_dump(mode="json"),
        )
        print(f"{doc.session_id}: {len(responses)} responses proofread")
    from app.settings import settings

    manifest = json.loads((src / "manifest.json").read_text())
    manifest["proofread"] = {
        "pipeline": "app.proofread.pipeline.proofread_answer (as the worker's proofread job)",
        "enhance_model": settings.enhance_model, "languagetool": sorted(versions),
        "source": str(args.out),
    }  # fmt: skip
    write_json(dst / "manifest.json", manifest)
    return 0


def seed_schema(args: argparse.Namespace, classifier: str, dsn: str) -> None:
    """Write the answers with the classifier's labels as a fixture and ingest it into `args.schema`.

    With --proofread the fixture is the test fixture tests/fixtures/scale_answers (its 40 labelled
    questions are kept); the raw answers go to a scratch folder next to the units. The schema is
    seeded by scripts/db/chips_fixture.py, as the tests do it: units, bge-m3 vectors, BM25, one
    session per (document, vignette) with a findings record.
    """
    sys.path.insert(0, str(ROOT / "scripts" / "db"))
    import chips_fixture
    import classify_sentence_targets

    labels = args.units / TIER / classify_sentence_targets.model_tag(classifier) / "labels"
    out = (
        chips_fixture.FIXTURE
        if args.proofread
        else args.units.parent / f"{args.units.name}_fixture"
    )
    out.mkdir(parents=True, exist_ok=True)
    questions = json.loads((chips_fixture.FIXTURE / "questions.json").read_text())["questions"]
    chips_fixture.export(args.out / "synthetic" / TIER, labels, out, questions)
    corpus = chips_fixture.ingest(
        chips_fixture.load(out), chips_fixture.IndexEmbeddings(), patients=False
    )
    with chips_fixture.seeded_schema(dsn, args.schema, corpus, keep=True):
        pass
    print(f"wrote {out}; seeded {args.schema}: {len(corpus.tables['units'])} units")


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
    ap.add_argument(
        "--stage", choices=["seed", "vignettes", "answers", "proofread", "build"], required=True
    )
    ap.add_argument(
        "--model",
        default="qwen3.8:27b",
        help="answers stage: writes experts 3-20 (21-32 use their persona file's model)",
    )
    ap.add_argument("--classifier", default="qwen3.5:9b", help="build stage")
    ap.add_argument(
        "--schema", default=None,
        help=f"build stage: Postgres schema to (re)load (default {SCHEMA}; {PROOFREAD_SCHEMA} with --proofread)",
    )  # fmt: skip
    ap.add_argument("--proofread-out", type=Path, default=PROOFREAD_OUT)
    ap.add_argument(
        "--proofread", action="store_true",
        help="build stage: build the proofread fixture (--proofread-out) instead of the raw one",
    )  # fmt: skip
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
    ap.add_argument("--experts", type=int, nargs="+", help="answers: only these experts (3-32)")
    ap.add_argument("--vignettes", nargs="+", help="answers: only these vignettes")
    ap.add_argument("--only", nargs="+", help="vignettes stage: only these scenario ids (N01 ...)")
    ap.add_argument(
        "--check", action="store_true", help="answers: print the answers, write nothing"
    )
    args = ap.parse_args(argv)
    if args.proofread:
        args.out = args.proofread_out
        if args.units == UNITS:
            args.units = PROOFREAD_UNITS
    args.schema = args.schema or (PROOFREAD_SCHEMA if args.proofread else SCHEMA)
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
    if args.stage == "proofread":
        return proofread_stage(args)
    return build_stage(args)


if __name__ == "__main__":
    sys.exit(main())
