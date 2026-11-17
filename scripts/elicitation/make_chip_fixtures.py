"""Chip fixtures: shared vignettes, then expert answers with highlights, toggles and chips.

Usage:
    python scripts/elicitation/make_chip_fixtures.py --stage vignettes
        # Claude writes the texts through the inbox; the same vignettes go to bronze and silver
    python scripts/elicitation/make_chip_fixtures.py --stage answers --tier silver
        # Claude answers through the inbox (one request per persona and vignette)
    python scripts/elicitation/make_chip_fixtures.py --stage answers --tier bronze \
        --answer-source ollama --model qwen3.6:35b-a3b [--only V001]
        # --only: check the replies, write nothing

Output: <out>/synthetic/<tier>/{vignettes,documents,claims}/ + manifest.json (default out:
data/fixtures_chips, kept apart from data/fixtures: its documents carry `highlights`, which the
base schema forbids). Like make_fixtures.py the script never calls an API: the inbox hands requests
to Claude Code agents, a reply that fails a rule is renamed *.rejected.json and asked for again.
Prompts: Persona_claude.v2, Synthetic_expert_answer.v4. No Q4 (out of scope for the chip test).
"""

import argparse
import json
import os
import re
import sys
from datetime import timedelta
from pathlib import Path

from chips_schema import (
    CHIP_QUESTIONS,
    CHIP_RE,
    DIRECTIONS,
    ChipDocument,
    ChipResponse,
    Highlight,
)
from elicitation_schema import ReferenceClaim, VariantInfo, Vignette, content_hash
from llm_clients import CachedGenerator, GenRequest, InboxGenerator, OllamaGenerator
from make_fixtures import (
    ANSWER_OPTIONS,
    EPOCH,
    PERSONA_OPTIONS,
    PERSONAS,
    SCENARIOS,
    Gen,
    Rejected,
    check_text,
    check_variant,
    derive_variant,
    design_from_output,
    fixture_dir,
    parse_json,
    write_json,
)
from prompt_loader import load_prompt
from pydantic import ValidationError

from app.vignettes.questions import QUESTIONS

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/fixtures_chips"
PERSONA_PROMPT, ANSWER_PROMPT = "Persona_claude.v2", "Synthetic_expert_answer.v4"
CLAUDE = "claude-sonnet-5-5 (Claude Code subagents)"
KINDS = ["clean", "verbose_hedged", "terse", "insufficient_info"]  # no bad_quote, no pair kind
OPEN_QUESTIONS = ("Q1", "Q2", "Q3", "Q5")

STYLE_RULES = {
    "clean": "Every point is clearly made and tied to the fragment it is about.",
    "verbose_hedged": "The same points, but wrapped in caveats, second thoughts and asides.",
    "terse": "Fragments and abbreviations, minimal; one line per answer is fine.",
    "insufficient_info": (
        "You decline to read traits into this text and say what is missing. Still mark the "
        "stretches you looked at (mostly 'unclear' or 'neutral'). No rating."
    ),
}
CHIP_HABITS = {
    "C1": "You cite a chip when a sentence is plainly about one fragment, but you often write in "
    "shorthand without one ('the sleep line', 'that bit') or with no pointer at all: about half "
    "of your sentences that concern a fragment carry no chip.",
    "C2": "You cite chips freely, usually one or two in a sentence about a fragment, but the "
    "general sentences (what is missing, base rates, your overall view) carry none.",
    "P1": "You cite a chip in most sentences about a fragment and keep the rest short, with none.",
    "P2": "You cite chips only sometimes; you often describe a fragment in your own words, or "
    "quote a few of its words in double quotes instead.",
    "P3": "You cite a chip the first time you mention a fragment in an answer and afterwards refer "
    "to it loosely ('that', 'the same line').",
}
LEAK = re.compile(
    r"\b(persona|as an ai|this clinician|the clinician in|variant [ab]|arm [ab]|test data)\b",
    re.IGNORECASE,
)
CANNOT_QUOTE = re.compile(r"\b(cannot|can't|can not|unable to|couldn't) (quote|pick|mark)", re.I)
TIER_QUALITY = {
    "silver": (
        "answers, highlights, toggles and reference claims written by Claude Sonnet subagents "
        "({model}); not expert-reviewed. Development metrics only, not reported results"
    ),
    "bronze": (
        "answers, highlights, toggles and claims written by a local model ({model}), claims in "
        "the same call as the answers: self-consistent by construction. Plumbing only, never "
        "accuracy"
    ),
}


# --- vignettes ---------------------------------------------------------------------------------


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
        MIN_WORDS=175 if "variant_change" in sc else 120,  # B drops sentences and must stay >= 120
    )
    return GenRequest(
        key=f"persona:{sc['id']}", system=p.system, user=p.user, json_mode=True,
        options=PERSONA_OPTIONS,
    )  # fmt: skip


def attempt(gen: Gen, req: GenRequest, build, inbox: Path):
    """gen.run, and a reply that failed a rule is set aside so the inbox asks for a new one."""
    result = gen.run(req, build)
    if result is None and gen.source == "claude":
        reply = inbox / "responses" / f"{req.key.replace(':', '.')}.json"
        if reply.exists():
            reply.rename(reply.with_name(reply.stem + ".rejected.json"))
            print(f"  set aside {reply.name}; the request is open again", file=sys.stderr)
    return result


def make_vignettes(gen: Gen, inbox: Path, only: list[str] | None) -> list[Vignette]:
    out: list[Vignette] = []
    for sc in SCENARIOS:
        pair = "variant_change" in sc

        def build(raw, sc=sc, pair=pair):
            data = parse_json(raw)
            text = str(data.get("text", "")).strip()
            check_text(text)
            if pair:  # A must allow a clean B
                b_text = derive_variant(text, sc["variant_drop"])
                check_variant(text, b_text)
                check_text(b_text)
            return text, design_from_output(data, sc, text)

        got = attempt(gen, persona_request(sc), build, inbox)
        if got is None:
            continue
        text, design = got
        questions = list(CHIP_QUESTIONS)
        out.append(
            Vignette(
                id=f"V{len(out) + 1:03d}", version=1, text=text,
                content_hash=content_hash(text), framing=sc["source"],
                design=design, question_ids=questions,
                variant=VariantInfo(pair_id=sc["id"], arm="A") if pair else None,
            )
        )  # fmt: skip
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
                    id=f"V{len(out) + 1:03d}", version=1, text=text_b,
                    content_hash=content_hash(text_b), framing=sc["source"],
                    design=design_b, question_ids=questions,
                    variant=VariantInfo(pair_id=sc["id"], arm="B", change=sc["variant_change"]),
                )
            )  # fmt: skip
    return out


# --- answers -----------------------------------------------------------------------------------


def answer_request(v: Vignette, kind: str, persona_id: str, persona: str) -> GenRequest:
    questions = "\n".join(
        f"{q}: {QUESTIONS[q].text}" + (" (answer in overall_rating)" if q == "Q6" else "")
        for q in v.question_ids
    )
    p = load_prompt(ANSWER_PROMPT).fill(
        PERSONA=persona, STYLE_RULE=STYLE_RULES[kind], CHIP_HABIT=CHIP_HABITS[persona_id],
        FRAMING=v.framing, VIGNETTE_TEXT=v.text, QUESTIONS=questions,
    )  # fmt: skip
    return GenRequest(
        key=f"answer:{v.id}:{kind}:{persona_id}", system=p.system, user=p.user, json_mode=True,
        options=ANSWER_OPTIONS,
    )  # fmt: skip


def parse_highlights(raw, text: str) -> list[Highlight]:
    if not isinstance(raw, list) or not 2 <= len(raw) <= 8:
        raise Rejected("highlights must be a list of 2 to 8")
    out = []
    for n, h in enumerate(raw, 1):
        if not isinstance(h, dict) or type(h.get("chip")) is not int or h["chip"] != n:
            raise Rejected(f"highlight {n}: chip numbers must be 1, 2, ... in order")
        t = h.get("text")
        if not isinstance(t, str) or not t.strip() or t.strip() not in text:
            raise Rejected(f"highlight {n}: not an exact substring of the vignette: {t!r}")
        t = t.strip()
        if not 2 <= len(t.split()) <= 40:
            raise Rejected(f"highlight {n}: {len(t.split())} words")
        if h.get("direction") not in DIRECTIONS:
            raise Rejected(f"highlight {n}: direction {h.get('direction')!r}")
        start = text.index(t)
        out.append(
            Highlight(chip=n, text=t, span=(start, start + len(t)), direction=h["direction"])
        )
    if len({h.text for h in out}) != len(out):
        raise Rejected("two highlights with the same text")
    return out


def chip_answer_pieces(data: dict, v: Vignette, kind: str, forbidden: re.Pattern | None):
    """Validate a reply: (answers, highlights, rating, insufficient, claims)."""
    answers = data.get("answers")
    if not isinstance(answers, dict):
        raise Rejected("no 'answers' object")
    clean = {}
    for qid in OPEN_QUESTIONS:
        value = answers.get(qid)
        if not isinstance(value, str) or not value.strip():
            raise Rejected(f"answer {qid} missing or blank")
        clean[qid] = value.strip()
    if "Q4" in answers:
        raise Rejected("Q4 is out of scope")
    highlights = parse_highlights(data.get("highlights"), v.text)
    declared = {h.chip for h in highlights}
    used = {int(n) for a in clean.values() for n in CHIP_RE.findall(a)}
    if used - declared:
        raise Rejected(f"chips {sorted(used - declared)} are not highlights")
    if not used and kind != "insufficient_info":
        raise Rejected("no chip is cited in any answer")

    alltext = " ".join(clean.values())
    if leak := LEAK.search(alltext):
        raise Rejected(f"persona or design talk: {leak.group()!r}")
    if CANNOT_QUOTE.search(clean["Q1"]):
        raise Rejected("Q1 says it cannot pick fragments, but highlights were marked")
    if forbidden:
        seen = {m.group().lower() for m in forbidden.finditer(alltext)}
        leaked = {w for w in seen if w not in v.text.lower()}
        if leaked:
            raise Rejected(f"answer mentions what this variant removed: {sorted(leaked)}")

    insufficient = data.get("insufficient_information") is True
    rating = data.get("overall_rating")
    if insufficient:
        rating = None
    elif not (type(rating) is int and 1 <= rating <= 5):
        raise Rejected(f"overall_rating {rating!r} is not 1-5 and not insufficient")
    if kind == "insufficient_info" and not insufficient:
        raise Rejected("insufficient_info must set insufficient_information")

    raw_claims = data.get("gold_claims") or []
    if not isinstance(raw_claims, list):
        raise Rejected("gold_claims is not a list")
    claims = []
    for c in raw_claims:
        if not isinstance(c, dict):
            raise Rejected(f"gold claim is not an object: {c!r}")
        span = c.get("quoted_span_text")
        if span is not None and span not in v.text:
            raise Rejected(f"claim span not an exact substring: {span!r}")
        if c.get("question_id") not in OPEN_QUESTIONS:
            raise Rejected(f"claim question_id {c.get('question_id')!r}")
        if CHIP_RE.search(str(c.get("claim", ""))):
            raise Rejected("a claim contains a chip token")
        try:
            claims.append(
                ReferenceClaim(
                    vignette_id=v.id, question_id=c["question_id"], claim_text=c.get("claim"),
                    quoted_span_text=span, trait=c.get("trait"), condition=c.get("condition"),
                    direction=c.get("direction") or None,
                )
            )  # fmt: skip
        except (ValidationError, TypeError) as e:
            raise Rejected(f"bad reference claim: {e}") from e
    if not claims and kind != "insufficient_info":
        raise Rejected("no reference claims")
    return clean, highlights, rating, insufficient, claims


# What variant B of S05 removed. Only the specific words count: "sleep" and "night" are ordinary
# differential-diagnosis words that the question text itself uses.
VARIANT_LEAK = re.compile(r"\b(newborn|baby|infant|broken nights?)\b", re.IGNORECASE)


def forbidden_for(v: Vignette) -> re.Pattern | None:
    """Words that variant B removed from A: an answer to B must not use them."""
    return VARIANT_LEAK if v.variant and v.variant.arm == "B" else None


# The local model never sets insufficient_information when told to decline (smoke test, 35b: four
# of four attempts rejected), so bronze rotates three styles; silver covers the fourth.
KINDS_BY_TIER = {"silver": KINDS, "bronze": KINDS[:3]}


def kind_for(doc_i: int, vig_i: int, seed: int, tier: str) -> str:
    kinds = KINDS_BY_TIER[tier]
    return kinds[(doc_i + vig_i + seed) % len(kinds)]


def make_document(doc_i, vignettes, gen: Gen, tier: str, inbox: Path, seed: int, skipped: list):
    expert_id, session_id = f"SYN-{doc_i + 1:03d}", f"DOC-SYN-{doc_i + 1:04d}"
    persona_id, persona = PERSONAS[tier][doc_i]
    day = EPOCH + timedelta(days=doc_i)
    clock, responses, claims_out = day, [], []
    for vig_i, v in enumerate(vignettes):
        kind = kind_for(doc_i, vig_i, seed, tier)
        req = answer_request(v, kind, persona_id, persona)
        forbidden = forbidden_for(v)
        got = attempt(
            gen,
            req,
            lambda raw, v=v, k=kind, f=forbidden: chip_answer_pieces(parse_json(raw), v, k, f),
            inbox,
        )
        if got is None:
            skipped.append(req.key)
            continue
        answers, highlights, rating, insufficient, claims = got
        started = clock + timedelta(minutes=1)
        clock = started + timedelta(minutes=4 + len(answers["Q1"]) // 80)
        responses.append(
            ChipResponse(
                vignette_id=v.id, vignette_version=v.version, vignette_hash=v.content_hash,
                expert_id=expert_id, answers=answers, highlights=highlights,
                rating=rating, insufficient_information=insufficient, started_at=started,
                submitted_at=clock,
            )
        )  # fmt: skip
        claims_out += claims
    return responses, claims_out, session_id, expert_id, day


# --- main --------------------------------------------------------------------------------------


def read_manifest(path: Path, tier: str) -> dict:
    return json.loads(path.read_text()) if path.exists() else {"tier": tier, "entries": []}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--stage", choices=["vignettes", "answers"], required=True)
    ap.add_argument("--tier", choices=["bronze", "silver"], help="answers stage")
    ap.add_argument("--answer-source", choices=["claude", "ollama"], default="claude")
    ap.add_argument("--model", default="qwen3.6:35b-a3b", help="for --answer-source ollama")
    ap.add_argument(
        "--base-url", default=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    )
    ap.add_argument("--inbox", type=Path, default=ROOT / "data/inbox")
    ap.add_argument("--cache", type=Path, default=ROOT / "data/cache")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--allow-partial", action="store_true", help="write what passed (bronze)")
    ap.add_argument(
        "--only", nargs="+", help="answers: only these vignette ids; checks, writes nothing"
    )
    args = ap.parse_args(argv)

    log: list[str] = []
    accepted: dict[str, str] = {}
    attempts: dict[str, int] = {}

    if args.stage == "vignettes":
        gen = Gen("claude", InboxGenerator(args.inbox), 0, args.seed, log, accepted, attempts)
        vignettes = make_vignettes(gen, args.inbox, None)
        if len(vignettes) != 14:
            print(f"{len(vignettes)}/14 vignettes ready; waiting:\n  " + "\n  ".join(log))
            return 1
        for tier in ("bronze", "silver"):
            out = fixture_dir(tier, "synthetic", args.out)
            for v in vignettes:
                write_json(out / "vignettes" / f"{v.id}.json", v.model_dump(mode="json"))
            entries = [
                dict(id=v.id, kind="vignette", tier=tier, source="claude", prompt=PERSONA_PROMPT,
                     model=CLAUDE, seed=args.seed, path=f"vignettes/{v.id}.json",
                     track=v.design.track, origin=v.design.origin)
                for v in vignettes
            ]  # fmt: skip
            quality = TIER_QUALITY[tier].format(model="see entries")
            write_json(
                out / "manifest.json",
                dict(source="synthetic", tier=tier, quality=quality, entries=entries),
            )
        print(f"wrote {len(vignettes)} vignettes to bronze and silver in {args.out}")
        return 0

    if not args.tier:
        raise SystemExit("--tier is required for the answers stage")
    out = fixture_dir(args.tier, "synthetic", args.out)
    vignettes = [
        Vignette.model_validate_json(p.read_text())
        for p in sorted((out / "vignettes").glob("V*.json"))
    ]
    if not vignettes:
        raise SystemExit(f"no vignettes in {out}: run --stage vignettes first")
    if args.only:
        vignettes = [v for v in vignettes if v.id in args.only]
    if args.answer_source == "claude":
        generator = InboxGenerator(args.inbox)
    else:
        generator = CachedGenerator(OllamaGenerator(args.base_url, args.model), args.cache)
    gen = Gen(args.answer_source, generator, args.retries, args.seed, log, accepted, attempts)
    skipped: list[str] = []
    docs = []
    for doc_i in range(len(PERSONAS[args.tier])):
        responses, claims, session_id, expert_id, day = make_document(
            doc_i, vignettes, gen, args.tier, args.inbox, args.seed, skipped
        )
        docs.append((responses, claims, session_id, expert_id, day))
        print(f"{session_id}: {len(responses)}/{len(vignettes)} answers", file=sys.stderr)
    if args.only:
        for responses, claims, *_ in docs:
            for r in responses:
                print(f"{r.vignette_id}: {len(r.highlights)} highlights "
                      f"{[h.direction for h in r.highlights]}, chips "
                      f"{sorted({int(n) for a in r.answers.values() for n in CHIP_RE.findall(a)})},"
                      " "
                      f"rating {r.rating}, {len(claims)} claims")  # fmt: skip
        print(f"skipped {skipped}" if skipped else "all fine; nothing written (--only)")
        return 1 if skipped else 0
    if skipped and not args.allow_partial:
        print(
            f"{len(skipped)} answers missing, nothing written:\n  " + "\n  ".join(sorted(skipped))
        )
        return 1

    manifest = read_manifest(out / "manifest.json", args.tier)
    manifest["entries"] = [e for e in manifest["entries"] if e["kind"] == "vignette"]
    model = CLAUDE if args.answer_source == "claude" else f"ollama:{args.model}"
    manifest["quality"] = TIER_QUALITY[args.tier].format(model=model)
    for responses, claims, session_id, expert_id, day in docs:
        if not responses:
            continue
        doc = ChipDocument(
            session_id=session_id, expert_id=expert_id, created_at=day,
            vignettes=vignettes, responses=responses,
        )  # fmt: skip
        write_json(out / "documents" / f"{session_id}.json", doc.model_dump(mode="json"))
        write_json(out / "claims" / f"{session_id}.claims.json", [c.model_dump() for c in claims])
        for kind, rel in (("document", f"documents/{session_id}.json"),
                          ("claims", f"claims/{session_id}.claims.json")):  # fmt: skip
            manifest["entries"].append(
                dict(id=session_id, kind=kind, tier=args.tier, source=args.answer_source,
                     prompt=ANSWER_PROMPT, model=model, seed=args.seed, path=rel)
            )  # fmt: skip
    manifest["rejections"], manifest["attempts"] = log, attempts
    manifest["skipped"] = sorted(skipped)
    write_json(out / "manifest.json", manifest)
    print(f"[{args.tier}] wrote {len(docs)} documents to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
