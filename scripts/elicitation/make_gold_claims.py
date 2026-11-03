"""Reference claims for the gold answers, written by a Claude agent through the inbox.

Usage: python scripts/elicitation/make_gold_claims.py [--tier gold] [--inbox data/inbox]

For every gold document without a claims file and every vignette in it, one request
(prompts/Gold_reference_claims.v1.md) goes to <inbox>/requests/claims.<session>.<vignette>.md. A
Claude Code agent writes the JSON reply to <inbox>/responses/ under the same name; run this again
until nothing is waiting. A reply that breaks a rule (claim of a question the expert did not answer,
a quote that is not an exact piece of the text, a bad direction) is renamed to *.rejected.json and
requested again. When every reply of a document is in, the claims are written to
data/fixtures/<source>/<tier>/claims/<session>.claims.json. They are the agent's reading of the
human's answers, not confirmed by the expert.
"""

import argparse
import contextlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from llm_clients import AwaitingResponse, GenRequest, InboxGenerator
from make_fixtures import Rejected, fixture_dir, parse_json, write_json
from prompt_loader import load_prompt
from pydantic import ValidationError

from app.elicitation.questions import QUESTIONS_BY_ID, describe_shift, render_question
from app.elicitation.schema import ElicitationDocument, ReferenceClaim, Response, Vignette

ROOT = Path(__file__).resolve().parents[2]
PROMPT = "Gold_reference_claims.v1"


def answers_block(v: Vignette, r: Response) -> str:
    parts = []
    for q in v.question_ids:
        question = f"{q}: {render_question(QUESTIONS_BY_ID[q], v.q4_whatif)}"
        if q == "Q4" and r.q4 is not None:
            lines = [question]
            if r.q4.hypothesis:
                lines.append(f"Hypothesis so far: {r.q4.hypothesis}")
            shift = describe_shift(r.q4.shift, r.q4.toward, r.q4.other_explanation)
            lines.append(
                f"Answer: my hypothesis {shift.split(' ', 1)[1]} ({shift.split(' ', 1)[0]})"
            )
            if q in r.answers:
                lines.append(f"Why: {r.answers[q]}")
            parts.append("\n".join(lines))
        elif q in r.answers:
            parts.append(f"{question}\nAnswer: {r.answers[q]}")
    if r.insufficient_information:
        parts.append("Overall rating: insufficient information")
    elif r.rating is not None:
        parts.append(f"Overall rating: {r.rating} of 5")
    return "\n\n".join(parts)


def claims_request(session_id: str, v: Vignette, r: Response) -> GenRequest:
    p = load_prompt(PROMPT).fill(VIGNETTE_TEXT=v.text, ANSWERS=answers_block(v, r))
    return GenRequest(
        key=f"claims:{session_id}:{v.id}", system=p.system, user=p.user, json_mode=True
    )


def check_claims(raw: str, v: Vignette, r: Response) -> list[ReferenceClaim]:
    """The agent's reply as ReferenceClaims; raises Rejected with the reason."""
    items = parse_json(raw).get("claims")
    if not isinstance(items, list):
        raise Rejected("no 'claims' list")
    claims = []
    for c in items:
        if not isinstance(c, dict):
            raise Rejected(f"claim is not an object: {c!r}")
        if c.get("question_id") not in r.answers:
            raise Rejected(f"claim for {c.get('question_id')!r}, which has no answer")
        span = c.get("quoted_span_text")
        if span is not None and span not in v.text:
            raise Rejected(f"span is not an exact piece of the text: {span!r}")
        try:
            claims.append(
                ReferenceClaim(
                    vignette_id=v.id,
                    question_id=c["question_id"],
                    claim_text=c.get("claim"),
                    quoted_span_text=span,
                    trait=c.get("trait"),
                    condition=c.get("condition"),
                    direction=c.get("direction") or None,
                )
            )
        except (ValidationError, TypeError) as e:
            raise Rejected(f"bad claim: {e}") from e
    if not claims and r.answers:
        raise Rejected("no claims for a response that has answers")
    return claims


def add_manifest_entry(tier_dir: Path, session_id: str) -> None:
    path = tier_dir / "manifest.json"
    manifest = json.loads(path.read_text()) if path.exists() else {"tier": tier_dir.name}
    entries = manifest.setdefault("entries", [])
    if not any(e["id"] == session_id and e["kind"] == "claims" for e in entries):
        entries.append(
            dict(id=session_id, kind="claims", tier=tier_dir.name, source="claude-agent",
                 prompt=PROMPT, model="claude-agent", seed=None, member_checked=False,
                 created_at=datetime.now(UTC).isoformat(timespec="seconds"),
                 path=f"claims/{session_id}.claims.json")
        )  # fmt: skip
        write_json(path, manifest)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tier", default="gold")
    ap.add_argument("--source", default="synthetic", choices=["synthetic", "reddit"])
    ap.add_argument("--inbox", type=Path, default=ROOT / "data/inbox")
    args = ap.parse_args(argv)
    tier_dir = fixture_dir(args.tier, args.source)
    inbox = InboxGenerator(args.inbox)
    waiting: list[str] = []
    for path in sorted((tier_dir / "documents").glob("DOC-*.json")):
        out = tier_dir / "claims" / f"{path.stem}.claims.json"
        if out.exists():
            continue
        doc = ElicitationDocument.model_validate_json(path.read_text())
        shown = {v.id: v for v in doc.vignettes}
        claims: list[ReferenceClaim] = []
        complete = True
        for r in doc.responses:
            req = claims_request(doc.session_id, shown[r.vignette_id], r)
            try:
                claims += check_claims(inbox.generate(req), shown[r.vignette_id], r)
            except AwaitingResponse as e:
                waiting.append(str(e))
                complete = False
            except Rejected as e:
                reply = args.inbox / "responses" / (req.key.replace(":", ".") + ".json")
                reply.rename(reply.with_suffix(".rejected.json"))
                waiting.append(f"{req.key}: reply rejected ({e}); write a new one")
                with contextlib.suppress(AwaitingResponse):
                    inbox.generate(req)  # writes the request again
                complete = False
        if complete:
            write_json(out, [c.model_dump() for c in claims])
            add_manifest_entry(tier_dir, doc.session_id)
            print(f"wrote {out.relative_to(ROOT)} ({len(claims)} claims)")
    if waiting:
        print(f"\n{len(waiting)} waiting for a Claude agent (requests in {args.inbox}/requests):")
        print("\n".join(f"  {w}" for w in waiting))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
