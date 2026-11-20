"""Build synthetic ElicitationDocuments and reference claims that look like real session output.

Usage:
    python scripts/elicitation/make_fixtures.py --persona-source file --answer-source file
        # no model
    python scripts/elicitation/make_fixtures.py --persona-source ollama --answer-source ollama \
        --model qwen3.5:9b
    python scripts/elicitation/make_fixtures.py --source reddit --answer-source ollama \
        [--reddit-vignettes 12] [--reddit-pool data/raw/reddit_adhd.jsonl] [--n-documents 0]
    python scripts/elicitation/make_fixtures.py --dry-run

Sources (see llm_clients.py):
    file    pre-written outputs from --persona-dir / --answer-dir (local samples in tests/, gitignored)
    ollama  instruct model on a local Ollama, with the Persona_claude / Synthetic_expert_answer
            prompts
    local   persona only: BASE model, raw completion, Persona_base_fewshot prompt and
            data/raw/seed_pool.jsonl
    claude  a Claude agent in the loop: requests are written to --inbox/requests, replies are read
            from --inbox/responses; the script itself never calls an API

Tiers (notes/fixtures.md): answers and reference claims are only as trustworthy as their author.
    bronze  small local model (ollama / its samples)   plumbing and regression tests only
    silver  Claude instances (claude / its samples)    development metrics
    gold    real expert answers - cannot be generated here

Text sources (--source): synthetic = model-written vignettes; reddit = real r/ADHD posts only
(scripts/elicitation/fetch_reddit_pool.py makes the pool). The two never mix in one run.

Output: <out>/<source>/<tier>/{vignettes,documents,claims}/ + manifest.json, and <out>/edge_cases/
(default out: data/fixtures). --n-documents 0 writes the vignettes only. Same arguments and
--seed reproduce the same files; model outputs are cached in data/cache/.
"""

import argparse
import json
import os
import random
import re
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from elicitation_schema import (
    MAX_WORDS,
    MIN_WORDS,
    SCHEMA_VERSION,
    Confounder,
    ElicitationDocument,
    PlantedCue,
    QuestionId,
    ReferenceClaim,
    Response,
    ShiftAnswer,
    VariantInfo,
    Vignette,
    VignetteDesign,
    content_hash,
)
from leak_terms import find_leaks
from llm_clients import (
    AwaitingResponse,
    CachedGenerator,
    FileGenerator,
    Generator,
    GenRequest,
    InboxGenerator,
    ModelRefused,
    OllamaGenerator,
)
from prompt_loader import load_prompt
from pydantic import ValidationError
from reddit_posts import load_pool as load_reddit_pool
from reddit_posts import pick_posts

from app.vignettes.questions import QUESTIONS, SHIFT_LABELS, TOWARD_LABELS, render_question

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "data/fixtures"
CHIP_SOURCE = "chips"
SOURCES = ("synthetic", "reddit")


def fixture_dir(tier: str, source: str = "synthetic", root: Path = FIXTURES) -> Path:
    """data/fixtures/<source>/<tier>: where one tier of one text source lives. The chip fixtures
    are kept apart (see make_chip_fixtures.py), so `chips` is data/fixtures_chips/synthetic."""
    if source == CHIP_SOURCE:
        return root.parent / "fixtures_chips" / "synthetic" / tier
    return root / source / tier


PERSONA_PROMPT = "Persona_claude.v1"
BASE_PROMPT = "Persona_base_fewshot.v1"
# v1 stays with bronze so cached qwen answers still rebuild (bronze vignettes have no what-if, so
# no Q4); silver uses v3: the stricter v2 plus the Q4 what-if scale
ANSWER_PROMPTS = {"bronze": "Synthetic_expert_answer.v1", "silver": "Synthetic_expert_answer.v3"}
EPOCH = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)  # fixed: fixtures must be reproducible

# --- scenarios: what each vignette is about (the model writes the text) -------------------------

NO_TRAITS = "none: this person has no notable attention or organisation difficulties"
SCENARIOS: list[dict[str, Any]] = [
    dict(
        id="S01",
        age=29,
        topic="a quarterly report due on Friday",
        source="personal_journal",
        situation="junior analyst at an insurance company, shares a flat",
        style="long run-on sentences, returns to the point late",
        traits="task_initiation: moderate; time_estimation: weak",
        confounders="moved flats two months ago and has been sleeping badly",
        max_cues=2,
        control=False,
    ),
    dict(
        id="S02",
        age=34,
        topic="organising her sister's birthday dinner",
        source="email",
        situation="primary school teacher, two cats",
        style="terse, lowercase, few commas",
        traits=NO_TRAITS,
        confounders="none",
        max_cues=0,
        control=True,
    ),
    dict(
        id="S03",
        age=41,
        topic="finally doing the tax return",
        source="forum_post",
        situation="freelance designer working from home",
        style="chatty, many asides in brackets",
        traits="novelty_seeking: moderate; sustained_attention_on_boring_tasks: weak",
        confounders="lost a parent in the spring and describes low mood in passing",
        max_cues=2,
        control=False,
    ),
    dict(
        id="S04",
        age=23,
        topic="a thesis chapter that is not getting written",
        source="forum_post",
        situation="master's student sharing a kitchen with three others",
        style="short paragraphs, self-deprecating humour",
        traits="distractibility: moderate; working_memory: weak",
        confounders="drinks a lot of coffee and has exam anxiety",
        max_cues=2,
        control=False,
    ),
    dict(
        id="S06",
        age=52,
        topic="packing for a house move next month",
        source="email",
        situation="accountant, moving to a smaller house",
        style="orderly, formal, a few worried asides",
        traits=NO_TRAITS,
        confounders="clear anxiety about the move",
        max_cues=0,
        control=True,
    ),
    # --- text_analysis track: how a clinician reads traits in a patient's own text. The RAG corpus
    # holds criteria, guidelines and two reviews of discourse/pragmatics in ADHD (child and lifespan
    # task-based studies); it has nothing on reading free adult text, which these vignettes probe.
    dict(
        id="T01",
        track="text_analysis",
        trait_key="discourse_tangentiality",
        knowledge_target=(
            "Telling goal-loss digression that eventually resolves from anxious rumination that "
            "circles one worry, in free adult text (textual markers, not diagnostic criteria)."
        ),
        age=33,
        topic="explaining why last week's project handover went wrong",
        source="email",
        situation="marketing coordinator writing to a friend",
        style="digressive: side stories, circles back to the point late, then apologises",
        traits="discourse_tangentiality: moderate; time_estimation: weak",
        confounders="has been ruminating about a conflict with a colleague",
        max_cues=2,
        control=False,
    ),
    dict(
        id="T02",
        track="text_analysis",
        trait_key="time_estimation",
        knowledge_target=(
            "Reading time language (vague quantifiers, 'just' tasks, retrospective "
            "underestimation) as evidence of time-estimation difficulty versus workload or "
            "avoidance."
        ),
        age=45,
        topic="why jobs keep overrunning and invoices go out late",
        source="forum_post",
        situation="self-employed electrician",
        style="matter of fact, lots of 'about', 'a bit', 'soon'",
        traits="time_estimation: strong; task_initiation: weak",
        confounders="the business has got busier and the writer works long tired days",
        max_cues=2,
        control=False,
    ),
    dict(
        id="T03",
        track="text_analysis",
        trait_key="task_initiation",
        knowledge_target=(
            "Weighing a help-seeking message: over-explaining or minimising style, borrowed "
            "opinions of others, and what the text cannot show (onset, breadth, impairment)."
        ),
        age=27,
        topic="asking for an appointment because things at work keep slipping",
        source="email",
        situation="recent graduate, three weeks into a new job, writing to a GP surgery",
        style="polite, over-explained, apologetic",
        traits="task_initiation: moderate; working_memory: weak",
        confounders="started a new job three weeks ago and feels under pressure",
        max_cues=2,
        control=False,
    ),
    dict(
        id="T04",
        track="text_analysis",
        trait_key="distractibility",
        knowledge_target=(
            "Separating fragmentation caused by medium, haste or fatigue from fragmentation that "
            "reflects attentional lapses (self-interruption mid-clause, lost referents)."
        ),
        age=31,
        topic="a note about the week, typed between tasks",
        source="personal_journal",
        situation="hospital nurse typing on a phone at the end of a night shift",
        style="fragments, unfinished sentences, self-interruptions, a few typos",
        traits="distractibility: moderate; working_memory: moderate",
        confounders="typing in a hurry on a phone after a night shift",
        max_cues=2,
        control=False,
    ),
    dict(
        id="T05",
        track="text_analysis",
        trait_key="emotional_reactivity",
        knowledge_target=(
            "Reading emotional reactivity in text: fast tone shifts with fast recovery versus "
            "persistent low mood, and what a single entry cannot show."
        ),
        age=26,
        topic="snapping at a colleague and then feeling awful about it",
        source="personal_journal",
        situation="retail manager writing after a bad day",
        style="tone swings within a paragraph, blunt then apologetic",
        traits="emotional_reactivity: moderate; quick_to_act: weak",
        confounders="low mood for several weeks after a break-up",
        max_cues=2,
        control=False,
    ),
    dict(
        id="T06",
        track="text_analysis",
        trait_key="retrospective_childhood",
        knowledge_target=(
            "Weighing retrospective childhood accounts in text (specific episodes versus generic "
            "labels, second-hand memories) for the childhood-onset requirement."
        ),
        age=39,
        topic="remembering how school went and what the teachers wrote on report cards",
        source="email",
        situation="writing a long email to a sibling",
        style="reflective, storytelling, vague on dates",
        traits="task_initiation: moderate; distractibility: moderate, recalled from childhood",
        confounders="many of the memories are second-hand, from stories the parents tell",
        max_cues=2,
        control=False,
    ),
    dict(
        id="T07",
        track="text_analysis",
        trait_key="discourse_tangentiality",
        knowledge_target=(
            "Hard negative: long, digressive but organised storytelling that must not be read as "
            "attentional (style versus trait)."
        ),
        age=68,
        topic="telling a neighbour about a fishing trip last summer",
        source="email",
        situation="retired bus driver who enjoys telling stories",
        style="warm, long-winded, many digressions that all return neatly to the story",
        traits=NO_TRAITS,
        confounders="naturally talkative and enjoys storytelling",
        max_cues=0,
        control=True,
    ),
    # A/B pair, last so the ids of everything above stay stable: B is derived from A in code.
    dict(
        id="S05",
        age=37,
        topic="getting the kids out of the door in the morning",
        source="personal_journal",
        situation="parent of two, a newborn at home",
        # short one-thought sentences, so that variant B can be A minus the newborn sentences
        style="plain, slightly tired, short sentences with one thought each",
        traits="time_estimation: moderate; task_initiation: weak",
        confounders="a newborn who wakes the household several times a night",
        max_cues=2,
        control=False,
        variant_change="The newborn and the broken nights are not mentioned.",
        # B is A without the sentences that match; the small model cannot do this edit reliably
        variant_drop=r"\b(newborn|baby|infant|nights?|wak(?:es?|ing)|woke|sleep\w*|feed\w*)\b",
    ),
]
# S05 yields an A/B pair (consecutive vignette ids), the others one vignette each.
TEXT_ANALYSIS = [sc for sc in SCENARIOS if sc.get("track") == "text_analysis"]

PERSONAS = {
    "bronze": [
        ("P1", "adult psychiatrist, 15 years, concise, uses abbreviations"),
        ("P2", "clinical psychologist, academic, hedges a lot, long answers"),
        ("P3", "GP with a special interest in adult neurodevelopment, practical, blunt"),
    ],
    "silver": [
        (
            "C1",
            "consultant psychiatrist, 18 years in an adult ADHD and neurodevelopmental service; "
            "reads referral letters and patients' own emails every week. Writes in clinical "
            "shorthand (hx, ddx, r/o, ?, ->), first person, skips what is obvious to a colleague, "
            "cross-refers to earlier answers, some answers are one line",
        ),
        (
            "C2",
            "clinical psychologist, 9 years doing adult neurodevelopmental assessments, reads a lot "
            "of patient-written pre-assessment questionnaires; full but plain sentences, thinks "
            "aloud, hedges with specifics ('I'd want to see...'), sometimes revises a point "
            "mid-answer, writes more on Q1/Q2 and less on later questions",
        ),
    ],
}
KINDS = ["clean", "verbose_hedged", "terse", "insufficient_info", "bad_quote"]
ANSWER_OPTIONS = {"temperature": 0.7, "num_predict": 3000, "num_ctx": 8192}
PERSONA_OPTIONS = {"temperature": 0.9, "top_p": 0.95, "num_predict": 1500, "num_ctx": 8192}


class Rejected(Exception):
    """A model output failed a fixture rule; the reason is reported and the call retried."""


# --- parsing and checking model output ---------------------------------------------------------


def parse_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise Rejected(f"not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise Rejected("JSON is not an object")
    return data


def ngrams(text: str, n: int) -> set[tuple[str, ...]]:
    words = re.findall(r"\w+", text.lower())
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def check_text(text: str) -> None:
    words = len(text.split())
    if not MIN_WORDS <= words <= MAX_WORDS:
        raise Rejected(f"{words} words, need {MIN_WORDS}-{MAX_WORDS}")
    if leaks := find_leaks(text):
        raise Rejected(f"leak terms: {leaks}")


def derive_variant(a_text: str, drop: str) -> str:
    """Variant B: A without the sentences matching `drop`, otherwise character for character."""
    parts = re.split(r"(?<=[.!?])(\s+)", a_text.strip())  # sentence, separator, sentence, ...
    pattern = re.compile(drop, re.IGNORECASE)
    kept = [
        parts[i] + (parts[i + 1] if i + 1 < len(parts) else "")
        for i in range(0, len(parts), 2)
        if not pattern.search(parts[i])
    ]
    return "".join(kept).strip()


def check_variant(a_text: str, b_text: str) -> None:
    """B is A with one change: not a copy, not a different text."""
    if b_text == a_text:
        raise Rejected("variant B is identical to A")
    if SequenceMatcher(None, a_text, b_text).ratio() < 0.5:
        raise Rejected("variant B is a rewrite, not A with one change")


def design_from_output(data: dict, scenario: dict, text: str) -> VignetteDesign:
    try:
        cues = [PlantedCue(**c) for c in data.get("planted_cues", [])]
        confs = [Confounder(**c) for c in data.get("confounders", [])]
        if scenario["control"]:
            cues = []  # a control has no traits to plant
        design = VignetteDesign(
            purpose=f"{scenario['topic']} ({'control' if scenario['control'] else 'traits'}: "
            f"{scenario['traits']})",
            planted_cues=cues,
            confounders=confs,
            is_control=scenario["control"],
            track=scenario.get("track", "general"),
            knowledge_target=scenario.get("knowledge_target"),
            population="adult" if scenario["age"] >= 18 else "child",
        )
    except (ValidationError, TypeError) as e:
        raise Rejected(f"bad design block: {e}") from e
    for span in [c.quote for c in cues] + [c.quote for c in confs]:
        if span not in text:
            raise Rejected(f"span not an exact substring: {span!r}")
    return design


def q4_whatif_from(data: dict) -> str | None:
    """The what-if Q4 asks about: written by the vignette author (the persona file's `q4_whatif`).
    There is no fallback: a quote from the text is not a what-if."""
    whatif = data.get("q4_whatif")
    if whatif is not None and (not isinstance(whatif, str) or not whatif.strip()):
        raise Rejected(f"q4_whatif is not a non-blank string: {whatif!r}")
    return whatif.strip() if whatif else None


def question_ids(q4_whatif: str | None) -> list[QuestionId]:
    """All questions; Q4 only when there is a what-if to ask about."""
    return [q.id for q in QUESTIONS.values() if q.id != "Q4" or q4_whatif]


def quoted_strings(text: str) -> list[str]:
    return [m for pair in re.findall(r'"([^"]{15,})"|“([^”]{15,})”', text) for m in pair if m]


def inject_misquote(q1: str, vignette_text: str, spans: list[str]) -> str:
    """Make one quoted fragment in Q1 slightly wrong (drop its middle word).

    Done in code, not by the model: small models do not misquote on purpose. The reference claim
    keeps the exact span, which is what an extractor should resolve the misquote to.
    """
    for fragment in [*spans, *quoted_strings(q1)]:
        words = fragment.split()
        if len(words) < 4 or fragment not in q1 or fragment not in vignette_text:
            continue
        mid = len(words) // 2
        broken = " ".join(words[:mid] + words[mid + 1 :])
        if broken not in vignette_text:
            return q1.replace(fragment, broken, 1)
    raise Rejected("no quoted fragment in Q1 that can be misquoted")


def q4_pieces(data: dict, answers: dict) -> tuple[ShiftAnswer, str | None]:
    """Validate the Q4 part of an expert-answer output: (scale answer, why or None)."""
    raw = data.get("q4")
    if not isinstance(raw, dict):
        raise Rejected("no 'q4' object although Q4 was asked")
    if type(raw.get("shift")) is not int:  # type(): True is not a shift
        raise Rejected(f"q4.shift {raw.get('shift')!r} is not an integer -2..2")
    try:
        q4 = ShiftAnswer(**{k: raw.get(k) for k in ShiftAnswer.model_fields if k in raw})
    except ValidationError as e:
        raise Rejected(f"bad q4: {e}") from e
    why = answers.get("Q4")
    why = why.strip() if isinstance(why, str) and why.strip() and q4.shift != 0 else None
    return q4, why


def answer_pieces(data: dict, vignette: Vignette, kind: str):
    """Validate an expert-answer output; returns (answers, rating, insufficient, claims, q4)."""
    answers = data.get("answers")
    if not isinstance(answers, dict):
        raise Rejected("no 'answers' object")
    open_ids = [
        q.id for q in QUESTIONS.values() if q.kind == "open" and q.id in vignette.question_ids
    ]
    clean = {}
    for qid in open_ids:
        value = answers.get(qid)
        if not isinstance(value, str) or not value.strip():
            raise Rejected(f"answer {qid} missing or blank")
        clean[qid] = value.strip()
    q4 = None
    if "Q4" in vignette.question_ids:
        q4, why = q4_pieces(data, answers)
        if why:
            clean["Q4"] = why

    insufficient = data.get("insufficient_information") is True
    rating = data.get("overall_rating")
    if insufficient:
        rating = None
    elif not (type(rating) is int and 1 <= rating <= 5):  # type(): True is not a rating
        raise Rejected(f"overall_rating {rating!r} is not 1-5 and not insufficient")
    if kind == "insufficient_info" and not insufficient:
        raise Rejected("insufficient_info fixture must set insufficient_information")

    raw_claims = data.get("gold_claims") or []
    if not isinstance(raw_claims, list):
        raise Rejected("gold_claims is not a list")
    claims = []
    for c in raw_claims:
        if not isinstance(c, dict):
            raise Rejected(f"gold claim is not an object: {c!r}")
        span = c.get("quoted_span_text")
        if span is not None and span not in vignette.text:
            raise Rejected(f"claim span not an exact substring: {span!r}")
        try:
            claims.append(
                ReferenceClaim(
                    vignette_id=vignette.id,
                    question_id=c.get("question_id"),
                    claim_text=c.get("claim"),
                    quoted_span_text=span,
                    trait=c.get("trait"),
                    condition=c.get("condition"),
                    direction=c.get("direction") or None,
                )
            )
        except (ValidationError, TypeError) as e:
            raise Rejected(f"bad reference claim: {e}") from e
    if not claims and kind != "insufficient_info":
        raise Rejected("no reference claims")

    if kind == "bad_quote":
        spans = [c.quoted_span_text for c in claims if c.quoted_span_text]
        clean["Q1"] = inject_misquote(clean["Q1"], vignette.text, spans)
    return clean, rating, insufficient, claims, q4


# --- running generators with retries -----------------------------------------------------------


@dataclass
class Gen:
    source: str
    generator: Generator
    retries: int
    seed: int
    log: list[str]
    accepted: dict[str, str]  # request key -> accepted raw output (for --export-samples)
    attempts: dict[str, int]

    def run(self, req: GenRequest, build):
        """Call, validate with `build(raw)`, retry with a new seed; None if every attempt fails."""
        for attempt in range(self.retries + 1):
            r = replace(req, seed=self.seed + attempt * 7919)
            try:
                raw = self.generator.generate(r)
                result = build(raw)
            except (Rejected, ModelRefused) as e:
                self.log.append(f"{req.key} attempt {attempt + 1}: {e}")
                print(f"  rejected {req.key} (attempt {attempt + 1}): {e}", file=sys.stderr)
                if self.source in ("file", "claude"):
                    return None  # nothing new would come back on a retry
                continue
            except (AwaitingResponse, FileNotFoundError) as e:
                self.log.append(f"{req.key}: {e}")
                print(f"  waiting/missing {req.key}: {e}", file=sys.stderr)
                return None
            self.accepted[req.key] = raw
            self.attempts[req.key] = attempt + 1
            return result
        return None


# --- building vignettes and documents ----------------------------------------------------------


def persona_request(sc: dict) -> GenRequest:
    p = load_prompt(PERSONA_PROMPT).fill(
        AGE=sc["age"],
        SITUATION=sc["situation"],
        TOPIC=sc["topic"],
        SOURCE_TYPE=sc["source"],
        STYLE=sc["style"],
        TRAITS=sc["traits"],
        CONFOUNDERS=sc["confounders"],
        MAX_CUES=sc["max_cues"],
        IF_VARIANT="",  # variants are derived in code (derive_variant)
        VARIANT_CHANGE="",
        VARIANT_A_TEXT="",
    )
    return GenRequest(
        key=f"persona:{sc['id']}",
        system=p.system,
        user=p.user,
        json_mode=True,
        options=PERSONA_OPTIONS,
    )


def local_request(sc: dict, pool: list[dict], seed: int):
    """Raw base-model prompt: 3 rotating leak-stripped examples + the entry to continue."""
    want = "control" if sc["control"] else "adhd"
    rng = random.Random(f"{seed}:{sc['id']}")
    candidates = [e for e in pool if e.get("label") == want]
    if len(candidates) < 3:
        raise SystemExit(f"seed pool has {len(candidates)} posts labelled {want!r}, need 3")
    shots = rng.sample(candidates, 3)
    entry = "=== ENTRY {n} ===\nAge: {age}\nSituation: {situation}\nOn my mind today: {topic}"
    examples = "\n\n".join(
        entry.format(n=i + 1, **{k: s.get(k, "") for k in ("age", "situation", "topic")})
        + "\n"
        + s["text"].strip()
        for i, s in enumerate(shots)
    )
    p = load_prompt(BASE_PROMPT).fill(
        EXAMPLES=examples, N=4, AGE=sc["age"], SITUATION=sc["situation"], TOPIC=sc["topic"]
    )
    s = p.meta["sampling"]
    opts = {
        "temperature": s["temperature"],
        "top_p": s["top_p"],
        "repeat_penalty": s["repeat_penalty"],
        "num_predict": s["max_tokens"],
        "stop": s["stop"],
    }
    return GenRequest(key=f"persona:{sc['id']}", user=p.user + "\n", raw=True, options=opts), shots


def make_vignettes(gen: Gen, args, pool) -> list[Vignette]:
    scenarios = SCENARIOS
    out: list[Vignette] = []
    for sc in scenarios:
        if len(out) >= args.n_vignettes:
            break
        pair = "variant_change" in sc
        if pair and len(out) + 2 > args.n_vignettes:
            continue
        shots = []
        if args.persona_source == "local":
            req, shots = local_request(sc, pool, args.seed)
        else:
            req = persona_request(sc)

        def build(raw, sc=sc, shots=shots, pair=pair):
            if args.persona_source == "local":
                text, data = raw.strip(), {}
                grams = set().union(*(ngrams(s["text"], 8) for s in shots))
                if ngrams(text, 8) & grams:
                    raise Rejected("copies an 8-gram from the few-shot examples")
            else:
                data = parse_json(raw)
                text = str(data.get("text", "")).strip()
            check_text(text)
            if pair:  # A must allow a clean B, else it is retried
                b_text = derive_variant(text, sc["variant_drop"])
                check_variant(text, b_text)
                check_text(b_text)
            design = design_from_output(data, sc, text)
            return text, design, q4_whatif_from(data)

        got = gen.run(req, build)
        if got is None:
            continue
        text, design, whatif = got
        vid = f"V{len(out) + 1:03d}"
        variant = VariantInfo(pair_id=sc["id"], arm="A") if pair else None
        out.append(
            Vignette(
                id=vid,
                version=1,
                text=text,
                content_hash=content_hash(text),
                framing=sc["source"],
                design=design,
                question_ids=question_ids(whatif),
                q4_whatif=whatif,
                variant=variant,
            )
        )
        if pair:
            a = out[-1]
            text_b = derive_variant(a.text, sc["variant_drop"])
            design_b = a.design.model_copy(
                update={
                    "planted_cues": [c for c in a.design.planted_cues if c.quote in text_b],
                    "confounders": [c for c in a.design.confounders if c.quote in text_b],
                }
            )
            out.append(
                Vignette(
                    id=f"V{len(out) + 1:03d}",
                    version=1,
                    text=text_b,
                    content_hash=content_hash(text_b),
                    framing=sc["source"],
                    design=design_b,
                    question_ids=question_ids(whatif),  # not tied to the text: B keeps it
                    q4_whatif=whatif,
                    variant=VariantInfo(pair_id=sc["id"], arm="B", change=sc["variant_change"]),
                )
            )
    return out


def kind_for(doc_i: int, vig_i: int, vignette: Vignette, seed: int) -> str:
    if vignette.variant and vignette.variant.arm == "B" and (doc_i + seed) % 2 == 0:
        return "pair_no_difference"
    return KINDS[(doc_i + vig_i + seed) % len(KINDS)]


Q4_SCALE = (
    "\n    (answer in `q4`: shift -2..+2 = with this, my hypothesis "
    + ", ".join(f"{k:+d} {v}" if k else f"0 {v}" for k, v in SHIFT_LABELS.items())
    + "; toward only for +1/+2: "
    + " | ".join(f"{k} ({v})" for k, v in TOWARD_LABELS.items())
    + '; a short why in answers["Q4"] unless the shift is 0)'
)


def answer_request(
    vignette: Vignette, kind: str, persona: tuple[str, str], prompt: str
) -> GenRequest:
    questions = "\n".join(
        f"{q.id}: {render_question(q, vignette.q4_whatif)}" + (Q4_SCALE if q.id == "Q4" else "")
        for q in QUESTIONS.values()
        if q.id in vignette.question_ids
    )
    p = load_prompt(prompt).fill(
        PERSONA=persona[1],
        FIXTURE_KIND="clean" if kind == "bad_quote" else kind,  # the misquote is injected later
        FRAMING=vignette.framing,
        VIGNETTE_TEXT=vignette.text,
        QUESTIONS=questions,
    )
    return GenRequest(
        key=f"answer:{vignette.id}:{kind}:{persona[0]}",
        system=p.system,
        user=p.user,
        json_mode=True,
        options=ANSWER_OPTIONS,
    )


def make_document(doc_i: int, vignettes: list[Vignette], gen: Gen, args, skipped: list[str]):
    expert_id = f"SYN-{doc_i + 1:03d}"
    session_id = f"DOC-SYN-{doc_i + 1:04d}"
    day = EPOCH + timedelta(days=doc_i)
    responses, claims_out = [], []
    clock = day
    for vig_i, v in enumerate(vignettes):
        kind = kind_for(doc_i, vig_i, v, args.seed)
        req = answer_request(v, kind, PERSONAS[args.tier][doc_i], ANSWER_PROMPTS[args.tier])
        got = gen.run(req, lambda raw, v=v, kind=kind: answer_pieces(parse_json(raw), v, kind))
        if got is None:
            skipped.append(req.key)
            continue
        answers, rating, insufficient, claims, q4 = got
        spans = sorted({c.quoted_span_text for c in claims if c.quoted_span_text})
        started = clock + timedelta(minutes=1)
        clock = started + timedelta(minutes=4 + (len(answers["Q1"]) // 80))
        responses.append(
            Response(
                vignette_id=v.id,
                vignette_version=v.version,
                vignette_hash=v.content_hash,
                expert_id=expert_id,
                answers=answers,
                quoted_fragments=spans,
                rating=rating,
                insufficient_information=insufficient,
                q4=q4,
                started_at=started,
                submitted_at=clock,
            )
        )
        claims_out += claims
    if not responses:
        return None
    doc = ElicitationDocument(
        session_id=session_id,
        expert_id=expert_id,
        created_at=day,
        vignettes=vignettes,
        responses=responses,
    )
    return doc, claims_out


# --- hand-written edge cases (no model) --------------------------------------------------------

EDGE_TEXT = (
    "I keep telling myself I will start the report tomorrow and then tomorrow turns into the "
    "next week. Yesterday I sat down at nine, opened the file, and by eleven I had tidied my "
    "desk, answered four emails nobody needed answered and looked up how long it takes to walk "
    "to Lisbon. The report itself is maybe two pages. My manager asked on Monday whether it was "
    "on track and I said yes, which was true in the sense that the file exists. We moved flats "
    "in March and I still have boxes in the hallway, and the new place is loud so I wake up at "
    "five most days and lie there. Anyway the deadline is Friday. I think I work better close "
    "to a deadline, I always have, ever since school. Last quarter I finished at two in the "
    "morning the night before and it was fine, nobody complained. This time I would like to "
    "not do that, but I also have not opened the file since Wednesday."
)


def edge_cases() -> dict[str, dict]:
    v = Vignette(
        id="V001",
        version=1,
        text=EDGE_TEXT,
        content_hash=content_hash(EDGE_TEXT),
        framing="personal_journal",
        question_ids=["Q1", "Q4", "Q6"],
        q4_whatif="the writer had started a new medication for low mood a month earlier",
        design=VignetteDesign(
            purpose="edge-case base",
            planted_cues=[
                PlantedCue(
                    quote="tomorrow turns into the next week",
                    trait="task_initiation",
                    strength="moderate",
                )
            ],
            confounders=[
                Confounder(
                    quote="the new place is loud so I wake up at five",
                    alternative_explanation="poor sleep after the move",
                )
            ],
        ),
    )
    t0 = EPOCH
    good = dict(
        vignette_id="V001",
        vignette_version=1,
        vignette_hash=v.content_hash,
        expert_id="SYN-900",
        answers={
            "Q1": "'tomorrow turns into the next week' - task initiation.",
            "Q4": "Low mood would explain the stalling as well as anything trait-like.",
        },
        quoted_fragments=["tomorrow turns into the next week"],
        rating=3,
        q4={
            "hypothesis": "long-standing trouble starting tasks",
            "shift": 1,
            "toward": "less_adhd",
            "other_explanation": None,
        },
        started_at=t0.isoformat(),
        submitted_at=(t0 + timedelta(minutes=9)).isoformat(),
    )
    base = dict(
        session_id="DOC-SYN-EDGE",
        expert_id="SYN-900",
        created_at=t0.isoformat(),
        schema_version=SCHEMA_VERSION,
        vignettes=[v.model_dump(mode="json")],
        responses=[good],
    )
    ElicitationDocument.model_validate(base)  # the base itself must be valid

    def variant(note, code, **patch):
        doc = json.loads(json.dumps(base))
        for path, value in patch.items():
            target = doc
            *head, last = path.split(".")
            for part in head:
                target = target[int(part)] if part.isdigit() else target[part]
            target[int(last) if last.isdigit() else last] = value
        return {"expected_error": code, "description": note, "document": doc}

    dup = json.loads(json.dumps(base))
    dup["responses"] = [good, good]
    return {
        "empty_answer": variant(
            "Q1 answer is blank", "empty_answer", **{"responses.0.answers": {"Q1": "   "}}
        ),
        "quote_not_in_vignette": variant(
            "quoted fragment is not in the vignette text",
            "quote_not_in_vignette",
            **{"responses.0.quoted_fragments": ["tomorrow turns into next week"]},
        ),
        "vignette_hash_mismatch": variant(
            "response hash differs from the shown vignette",
            "vignette_hash_mismatch",
            **{"responses.0.vignette_hash": "0" * 64},
        ),
        "unknown_question_id": variant(
            "answer for a question that does not exist",
            "unknown_question_id",
            **{"responses.0.answers": {"Q9": "x"}},
        ),
        "q4_why_without_shift": variant(
            "a Q4 why although the expert chose 0 (no change)",
            "q4_why_without_shift",
            **{"responses.0.q4.shift": 0, "responses.0.q4.toward": None},
        ),
        "gate_not_passed": variant(
            "Q4 and Q6 answered but Q1 (a gate question) not",
            "gate_not_passed",
            **{
                "responses.0.answers": {"Q4": "Low mood fits as well."},
                "responses.0.quoted_fragments": [],
            },
        ),
        "duplicate_response": {
            "expected_error": "duplicate_response",
            "description": "two responses to the same vignette",
            "document": dup,
        },
    }


# --- real posts as vignettes -------------------------------------------------------------------


def add_reddit_vignettes(vignettes: list[Vignette], args) -> list[Vignette]:
    """Append real r/ADHD posts that fit the text_analysis scenarios' target traits."""
    if not args.reddit_pool.exists():
        raise SystemExit(f"--reddit-pool {args.reddit_pool} does not exist")
    posts = load_reddit_pool(args.reddit_pool)
    targets = [sc for sc in TEXT_ANALYSIS if not sc["control"]]
    taken: set[str] = set()
    for i in range(args.reddit_vignettes):
        sc = targets[i % len(targets)]
        picked = pick_posts(posts, sc["trait_key"], 1, taken, args.seed)
        if not picked:
            print(f"  no reddit post fits {sc['trait_key']}", file=sys.stderr)
            continue
        post = picked[0]
        taken.add(post.id)
        vignettes.append(
            Vignette(
                id=f"V{len(vignettes) + 1:03d}",
                version=1,
                text=post.text,
                content_hash=content_hash(post.text),
                framing="forum_post",
                question_ids=question_ids(None),  # no hand-picked fragment for Q4
                design=VignetteDesign(
                    purpose=f"real r/ADHD post fitting {sc['trait_key']}; sentences naming the "
                    "construct, medication, links or handles were dropped",
                    track="text_analysis",
                    knowledge_target=sc["knowledge_target"],
                    origin="real_text",
                    source_ref=f"reddit:{post.id}",
                ),
            )
        )
    return vignettes


# --- tiers -------------------------------------------------------------------------------------

TIER_QUALITY = {
    "bronze": (
        "answers AND reference claims written by a small local LLM ({model}); the claims come "
        "from the same call that wrote the answers, so they are self-consistent by construction "
        "and not independent of the model that would run extraction; not expert-reviewed. Use for "
        "plumbing and regression tests only, never to report extraction accuracy"
    ),
    "silver": (
        "answers and reference claims written by Claude instances ({model}); not "
        "expert-reviewed. Use for development metrics, not for reported results"
    ),
}


def resolve_tier(args) -> str:
    tier = args.tier or ("silver" if args.answer_source == "claude" else "bronze")
    if tier == "gold":
        raise SystemExit(
            "tier gold is real expert answers (non-synthetic documents, expert-confirmed claims); "
            "it cannot be generated here - see notes/fixtures.md"
        )
    if args.answer_source == "ollama" and tier != "bronze":
        raise SystemExit("answers from a local model are bronze; use --tier bronze")
    if args.answer_source == "claude" and tier != "silver":
        raise SystemExit("answers from Claude instances are silver; use --tier silver")
    return tier


# --- output ------------------------------------------------------------------------------------


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n")


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--persona-source", choices=["file", "ollama", "local", "claude"], default="file"
    )
    ap.add_argument("--answer-source", choices=["file", "ollama", "claude"], default="file")
    ap.add_argument(
        "--tier", choices=["bronze", "silver", "gold"], help="default: by answer source"
    )
    ap.add_argument(
        "--source",
        choices=SOURCES,
        default="synthetic",
        help="vignette texts: model-written (synthetic) or real r/ADHD posts (reddit)",
    )
    ap.add_argument("--persona-dir", type=Path, default=ROOT / "tests/sample_inputs/personas")
    ap.add_argument("--answer-dir", type=Path, help="default: tests/sample_inputs/answers/<tier>")
    ap.add_argument("--inbox", type=Path, default=ROOT / "data/inbox")
    ap.add_argument("--seed-pool", type=Path, default=ROOT / "data/raw/seed_pool.jsonl")
    ap.add_argument(
        "--reddit-pool",
        type=Path,
        default=ROOT / "data/raw/reddit_adhd.jsonl",
        help="JSONL of r/ADHD posts (see reddit_posts.py)",
    )
    ap.add_argument(
        "--reddit-vignettes",
        type=int,
        help="--source reddit: number of real posts used as vignettes (default 12)",
    )
    ap.add_argument("--out", type=Path, default=FIXTURES)
    ap.add_argument("--cache", type=Path, default=ROOT / "data/cache")
    ap.add_argument(
        "--base-url", default=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    ap.add_argument("--model", default="qwen3.5:9b", help="instruct model for source 'ollama'")
    ap.add_argument(
        "--base-model", default="qwen3.5:9b", help="base model for persona-source local"
    )
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--n-vignettes", type=int, default=14, help="model-written vignettes")
    ap.add_argument("--n-documents", type=int, help="default: one per persona of the tier")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument(
        "--export-samples", type=Path, help="save accepted raw outputs as file-source inputs"
    )
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args(argv)


def make_generator(source: str, args, kind: str) -> Generator:
    if source == "file":
        return FileGenerator(args.persona_dir if kind == "persona" else args.answer_dir)
    if source == "claude":
        return InboxGenerator(args.inbox)
    model = args.base_model if source == "local" else args.model
    return CachedGenerator(OllamaGenerator(args.base_url, model), args.cache)


def export_samples(args, tier: str, accepted: dict[str, str], pg, ag) -> None:
    for sub, source, gen, prefix, prompt in (
        ("personas", args.persona_source, pg, "persona:", PERSONA_PROMPT),
        (f"answers/{tier}", args.answer_source, ag, "answer:", ANSWER_PROMPTS[tier]),
    ):
        folder = args.export_samples / sub
        for key, raw in accepted.items():
            if key.startswith(prefix):
                folder.mkdir(parents=True, exist_ok=True)
                (folder / f"{key.replace(':', '.')}.json").write_text(raw.strip() + "\n")
        if folder.exists():
            model = gen.name.split(":", 1)[-1] if ":" in gen.name else gen.name
            write_json(
                folder / "PROVENANCE.json",
                dict(model=model, source=source, prompt=prompt, seed=args.seed),
            )


def main(
    argv=None, persona_gen: Generator | None = None, answer_gen: Generator | None = None
) -> int:
    args = parse_args(argv)
    tier = args.tier = resolve_tier(args)
    n_personas = len(PERSONAS[tier])
    n_docs = n_personas if args.n_documents is None else args.n_documents
    args.n_documents = min(n_docs, n_personas)  # 0 = vignettes only
    args.answer_dir = args.answer_dir or ROOT / "tests/sample_inputs/answers" / tier
    if args.source == "reddit":
        args.n_vignettes = 0  # real posts only, no model-written texts
        args.reddit_vignettes = 12 if args.reddit_vignettes is None else args.reddit_vignettes
    elif args.reddit_vignettes:
        raise SystemExit("real posts are their own source: use --source reddit")
    else:
        args.reddit_vignettes = 0
    out = fixture_dir(tier, args.source, args.out)

    if args.dry_run:
        n_vig = args.n_vignettes + args.reddit_vignettes
        print(
            f"{args.source}/{tier}; persona source: {args.persona_source} -> up to "
            f"{args.n_vignettes} vignettes (scenarios {[s['id'] for s in SCENARIOS]}, S05 is an "
            f"A/B pair, {len(TEXT_ANALYSIS)} are text_analysis) + {args.reddit_vignettes} real "
            "r/ADHD posts"
        )
        print(
            f"answer source:  {args.answer_source} -> {args.n_documents} documents x ~{n_vig} "
            f"responses, one call each, kinds rotate over {KINDS} (+ pair_no_difference)"
        )
        print(
            "models: "
            f"{args.model if 'ollama' in (args.persona_source, args.answer_source) else '-'}"
            f" @ {args.base_url}; seed {args.seed}; out {out}"
        )
        print(f"edge cases (no model): {list(edge_cases())}")
        return 0

    pool = []
    if args.persona_source == "local":
        pool = [
            json.loads(line) for line in args.seed_pool.read_text().splitlines() if line.strip()
        ]

    log: list[str] = []
    accepted: dict[str, str] = {}
    attempts: dict[str, int] = {}
    pg = persona_gen or make_generator(args.persona_source, args, "persona")
    ag = answer_gen or make_generator(args.answer_source, args, "answer")
    mk = lambda src, g: Gen(src, g, args.retries, args.seed, log, accepted, attempts)  # noqa: E731

    print("vignettes ...", file=sys.stderr)
    vignettes = make_vignettes(mk(args.persona_source, pg), args, pool)
    if args.reddit_vignettes:
        vignettes = add_reddit_vignettes(vignettes, args)
    if not vignettes:
        print("no vignettes produced:\n  " + "\n  ".join(log), file=sys.stderr)
        return 1

    manifest = []
    created = EPOCH.isoformat()
    persona_prompt = BASE_PROMPT if args.persona_source == "local" else PERSONA_PROMPT
    for v in vignettes:
        write_json(out / "vignettes" / f"{v.id}.json", v.model_dump(mode="json"))
        real = v.design.origin == "real_text"
        manifest.append(
            dict(
                id=v.id,
                kind="vignette",
                tier=tier,
                source="reddit" if real else args.persona_source,
                prompt=None if real else persona_prompt,
                model=None if real else pg.name,
                seed=args.seed,
                created_at=created,
                path=f"vignettes/{v.id}.json",
                track=v.design.track,
                origin=v.design.origin,
            )
        )

    skipped: list[str] = []
    answers = mk(args.answer_source, ag)
    for doc_i in range(args.n_documents):
        print(f"document {doc_i + 1} ...", file=sys.stderr)
        made = make_document(doc_i, vignettes, answers, args, skipped)
        if made is None:
            skipped.append(f"DOC-SYN-{doc_i + 1:04d}")
            continue
        doc, claims = made
        write_json(out / "documents" / f"{doc.session_id}.json", doc.model_dump(mode="json"))
        write_json(
            out / "claims" / f"{doc.session_id}.claims.json", [c.model_dump() for c in claims]
        )
        for kind, rel in (
            ("document", f"documents/{doc.session_id}.json"),
            ("claims", f"claims/{doc.session_id}.claims.json"),
        ):
            manifest.append(
                dict(
                    id=doc.session_id,
                    kind=kind,
                    tier=tier,
                    source=args.answer_source,
                    prompt=ANSWER_PROMPTS[tier],
                    model=ag.name,
                    seed=args.seed,
                    created_at=created,
                    path=rel,
                )
            )

    for name, case in edge_cases().items():
        write_json(args.out / "edge_cases" / f"{name}.json", case)

    write_json(
        out / "manifest.json",
        dict(
            source=args.source,
            tier=tier,
            quality=TIER_QUALITY[tier].format(model=ag.name),
            entries=manifest,
            skipped=sorted(skipped),
            rejections=log,
            attempts=attempts,
        ),
    )
    if args.export_samples:
        export_samples(args, tier, accepted, pg, ag)

    n_docs = sum(1 for m in manifest if m["kind"] == "document")
    print(
        f"[{args.source}/{tier}] wrote {len(vignettes)} vignettes, {n_docs} documents, "
        f"{len(edge_cases())} edge cases to {args.out}"
        + (f"; skipped {len(skipped)}: {sorted(skipped)}" if skipped else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
