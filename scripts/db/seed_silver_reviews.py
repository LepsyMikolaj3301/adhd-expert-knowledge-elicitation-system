"""Development data: silver answers submitted by two experts and peer-reviewed by two
more, left in `peer_review` for the admin to decide and ingest by hand.

Run from backend/ (the dev password is never stored; the four experts all get it):
    SEED_PASSWORD='...' uv run python ../scripts/db/seed_silver_reviews.py \
        --admin-email you@example.com

Reads data/fixtures_chips/synthetic/silver/: the silver documents (answers of SYN-001 and
SYN-002), platform_seed.json (which vignettes, the Q4 answers, the reviewers and their votes and
comments) and platform_pairs.json (V009/V010: one pair of similar answers, one of divergent ones).
What-ifs come from scripts/elicitation/chip_whatifs.json.

Setup (users, vignettes, assignments) goes through the service layer as the admin; everything an
expert does goes through the real API in-process, so validation, audit events and state changes run
as they do in the UI. Every step skips what is already done: re-running continues where it stopped.
Refuses to run in production.
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select

from app.assignments.answers import AnswerPayload, clean_submission
from app.assignments.models import Assignment
from app.assignments.service import assign
from app.assignments.states import JOB_STATES, State
from app.core.db import session_factory
from app.jobs.worker import run_once
from app.main import app
from app.settings import settings
from app.users.models import Role, User
from app.users.service import create_user
from app.vignettes.models import VersionStatus, Vignette, VignetteVersion
from app.vignettes.schemas import VersionContent, VignetteCreate
from app.vignettes.service import create_vignette, publish_version

ROOT = Path(__file__).resolve().parents[2]
SILVER = ROOT / "data" / "fixtures_chips" / "synthetic" / "silver"
WHATIFS = ROOT / "scripts" / "elicitation" / "chip_whatifs.json"
DOCUMENTS = {"SYN-001": "DOC-SYN-0001.json", "SYN-002": "DOC-SYN-0002.json"}
ALL_QUESTIONS = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"]
JOB_TIMEOUT_S = 1800


def log(message: str) -> None:
    print(message, flush=True)


# --- content --------------------------------------------------------------------------------


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_vignette(code: str) -> dict[str, Any]:
    return load_json(SILVER / "vignettes" / f"{code}.json")


def silver_payload(response: dict[str, Any], q4: dict[str, Any]) -> dict[str, Any]:
    """A silver chip answer (no Q4) plus the Q4 written for it, as an AnswerPayload dict."""
    answers = dict(response["answers"])
    if q4["shift"] != 0:
        answers["Q4"] = q4["why"]
    return {
        "answers": answers,
        "highlights": response["highlights"],
        "q4": {
            "hypothesis": q4["hypothesis"],
            "shift": q4["shift"],
            "toward": q4.get("toward"),
            "other_explanation": q4.get("other_explanation"),
        },
        "rating": response["rating"],
        "insufficient_information": response["insufficient_information"],
    }


def build_payloads(seed: dict[str, Any], pairs: dict[str, Any]) -> dict[tuple[str, str], dict]:
    """(author, code) -> payload, each checked with the submit rules before anything is written."""
    silver = {
        author: {r["vignette_id"]: r for r in load_json(SILVER / "documents" / name)["responses"]}
        for author, name in DOCUMENTS.items()
    }
    payloads: dict[tuple[str, str], dict] = {}
    for code in seed["vignettes"]:
        text = fixture_vignette(code)["text"]
        for author in seed["authors"]:
            if code in pairs:
                payload = pairs[code][author]
            else:
                payload = silver_payload(silver[author][code], seed["q4"][author][code])
            clean_submission(AnswerPayload.model_validate(payload), ALL_QUESTIONS, text)
            payloads[(author, code)] = payload
    return payloads


# --- setup as the admin (service layer) -----------------------------------------------------


async def ensure_user(db, email: str, name: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.email == email.lower()))
    if user is not None:
        if user.role != Role.EXPERT:
            raise SystemExit(f"{email} exists but isn't an expert; refusing to use it.")
        log(f"  user {user.pseudonym} {email}: exists")
        return user
    user = await create_user(
        db, email=email, display_name=name, role=Role.EXPERT, password=password
    )
    log(f"  user {user.pseudonym} {email}: created")
    return user


async def ensure_version(
    db, code: str, summary: str, whatifs: dict[str, str], admin: User
) -> VignetteVersion:
    """The published version whose text is the fixture's. Creates and publishes it if new."""
    fixture = fixture_vignette(code)
    vignette = await db.scalar(select(Vignette).where(Vignette.code == code))
    if vignette is None:
        body = {k: fixture[k] for k in ("text", "framing", "variant", "design") if fixture.get(k)}
        created = VignetteCreate.model_validate(
            {**body, "code": code, "q4_whatif": whatifs[code], "patient_summary": summary}
        )
        content = VersionContent(**created.model_dump(exclude={"code"}))
        _, version = await create_vignette(db, code, content, admin)
        await publish_version(db, version.id, admin)
        log(f"  {code}: imported and published")
        return version
    versions = list(
        await db.scalars(
            select(VignetteVersion)
            .where(VignetteVersion.vignette_id == vignette.id)
            .where(VignetteVersion.text == fixture["text"])
            .order_by(VignetteVersion.version.desc())
        )
    )
    if not versions:
        raise SystemExit(f"{code} exists, but no version has the silver text the citations need.")
    version = versions[0]
    if version.status == VersionStatus.DRAFT:
        await publish_version(db, version.id, admin)
        log(f"  {code} v{version.version}: published")
    elif version.status != VersionStatus.PUBLISHED:
        raise SystemExit(f"{code} v{version.version} is {version.status}; can't assign it.")
    else:
        log(f"  {code} v{version.version}: published already")
    return version


async def ensure_assignment(db, version: VignetteVersion, expert: User, admin: User) -> UUID:
    found = await db.scalar(
        select(Assignment.id).where(
            Assignment.vignette_version_id == version.id,
            Assignment.expert_id == expert.id,
            Assignment.state != State.CANCELLED,
        )
    )
    if found is not None:
        return found
    (created,) = await assign(db, version.id, [expert.id], admin)
    return created.id


# --- the experts (API) ----------------------------------------------------------------------


class Api:
    """One logged-in user against the app in-process."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://seed/api/v1", timeout=600
        )

    async def login(self, email: str, password: str) -> None:
        await self.ok("POST", "/auth/login", json={"email": email, "password": password})

    async def ok(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self.client.request(method, path, **kwargs)
        if response.status_code >= 400:
            status = response.status_code
            raise SystemExit(f"{self.name}: {method} {path} -> {status} {response.text}")
        return response.json() if response.content else None

    async def close(self) -> None:
        await self.client.aclose()


async def state_of(api: Api, assignment_id: UUID) -> State:
    return State((await api.ok("GET", f"/assignments/{assignment_id}"))["state"])


async def answer(api: Api, assignment_id: UUID, payload: dict[str, Any]) -> None:
    """Start, save the draft and submit for proofreading, from wherever the assignment is."""
    state = await state_of(api, assignment_id)
    if state == State.ASSIGNED:
        await api.ok("POST", f"/assignments/{assignment_id}/start")
        state = State.IN_PROGRESS
    if state == State.IN_PROGRESS:
        current = await api.ok("GET", f"/assignments/{assignment_id}")
        version = (current.get("draft") or {}).get("version", 0)
        await api.ok(
            "PUT",
            f"/assignments/{assignment_id}/draft",
            json={"version": version, "payload": payload},
        )
        await api.ok("POST", f"/assignments/{assignment_id}/submit")


async def wait_for_proofreading(api_by_id: dict[UUID, Api], run_jobs: bool) -> None:
    """Runs (or waits for) the proofread jobs until no assignment of ours is in one."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + JOB_TIMEOUT_S
    while True:
        waiting = [i for i, api in api_by_id.items() if await state_of(api, i) in JOB_STATES]
        if not waiting:
            return
        if loop.time() > deadline:
            raise SystemExit(f"Proofreading still running after {JOB_TIMEOUT_S}s: {waiting}")
        log(f"  proofreading: {len(waiting)} waiting")
        if not (run_jobs and await run_once()):
            await asyncio.sleep(5)


async def submit_for_review(api: Api, assignment_id: UUID) -> None:
    """The author's check: link anything the proofreading left unlinked to the case, submit."""
    if await state_of(api, assignment_id) != State.PROOFREAD_CHECK:
        return
    view = await api.ok("GET", f"/assignments/{assignment_id}/proofread")
    overrides: dict[str, dict[str, list[str]]] = {}
    for item in view["items"]:
        if not item["linked"]:
            continue
        unlinked = {line["text"]: ["case"] for line in item["lines"] if not line["targets"]}
        if unlinked:
            overrides[item["question_id"]] = unlinked
    if overrides:
        count = sum(map(len, overrides.values()))
        log(f"    linked {count} unlinked line(s) to the case")
        await api.ok(
            "PUT",
            f"/assignments/{assignment_id}/proofread",
            json={
                "version": view["version"],
                "answers": {item["question_id"]: item["final"] for item in view["items"]},
                "overrides": overrides,
            },
        )
    await api.ok("POST", f"/assignments/{assignment_id}/submit-for-review")


async def review(
    assignment_id: UUID, plan: dict[str, Any], reviewers: dict[str, Api], author: Api
) -> None:
    """Votes (approve unless listed under `disapprove`) and comments, skipping what exists."""
    path = f"/assignments/{assignment_id}"
    for api in reviewers.values():
        await api.ok("POST", f"{path}/review/open")
    view = await author.ok("GET", f"{path}/answers")
    present = {a["question_id"] for a in view["answers"]}
    review_round = view["review_round"]
    for key, api in reviewers.items():
        refused = set(plan.get("disapprove", {}).get(key, []))
        for question_id in sorted(present):
            vote = "disapprove" if question_id in refused else "approve"
            await api.ok(
                "PUT",
                f"{path}/answers/{question_id}/vote",
                json={"vote": vote, "review_round": review_round},
            )

    created: list[str | None] = []
    for comment in plan.get("comments", []):
        api = author if comment["by"] == "author" else reviewers[comment["by"]]
        question_id = comment["q"]
        if question_id not in present:
            log(f"    skipped a comment on {question_id}: no such answer")
            created.append(None)
            continue
        current = await api.ok("GET", f"{path}/answers")
        thread = next(a for a in current["answers"] if a["question_id"] == question_id)
        mine = [c for c in thread["comments"] if c["is_mine"] and c["body"] == comment["body"]]
        if mine:
            created.append(mine[0]["id"])
            continue
        body: dict[str, Any] = {"body": comment["body"]}
        if comment.get("stance"):
            body["stance"] = comment["stance"]
        if "reply_to" in comment:
            body["parent_id"] = created[comment["reply_to"]]
        made = await api.ok("POST", f"{path}/answers/{question_id}/comments", json=body)
        created.append(made["id"])


# --- main -----------------------------------------------------------------------------------


async def main(args: argparse.Namespace) -> None:
    if settings.environment == "production":
        raise SystemExit("Refusing to seed development data in production.")
    password = os.environ.get(args.password_env, "")
    if not password:
        raise SystemExit(f"Set the experts' dev password in ${args.password_env}.")

    seed = load_json(SILVER / "platform_seed.json")
    pairs = load_json(SILVER / "platform_pairs.json")
    whatifs = load_json(WHATIFS)
    payloads = build_payloads(seed, pairs)
    log(f"{len(payloads)} payloads pass the submit rules")

    accounts = {**seed["authors"], **seed["reviewers"]}
    async with session_factory()() as db:
        admin = await db.scalar(select(User).where(User.email == args.admin_email.lower()))
        if admin is None or admin.role != Role.ADMIN:
            raise SystemExit(f"{args.admin_email} isn't an admin.")
        log("users:")
        users = {
            key: await ensure_user(db, a["email"], a["display_name"], password)
            for key, a in accounts.items()
        }
        log("vignettes:")
        versions = {
            code: await ensure_version(
                db, code, seed["patient_summaries"].get(code, ""), whatifs, admin
            )
            for code in seed["vignettes"]
        }
        assignments = {
            (author, code): await ensure_assignment(db, versions[code], users[author], admin)
            for (author, code) in payloads
        }
        await db.commit()

    apis = {key: Api(key) for key in accounts}
    try:
        for key, api in apis.items():
            await api.login(accounts[key]["email"], password)
        reviewers = {key: apis[key] for key in seed["reviewers"]}

        log("answering:")
        for (author, code), assignment_id in assignments.items():
            await answer(apis[author], assignment_id, payloads[(author, code)])
        await wait_for_proofreading(
            {i: apis[author] for (author, _), i in assignments.items()}, not args.no_run_jobs
        )

        log("submitting for review and reviewing:")
        for (author, code), assignment_id in assignments.items():
            log(f"  {author}/{code}")
            await submit_for_review(apis[author], assignment_id)
            state = await state_of(apis[author], assignment_id)
            if state != State.PEER_REVIEW:
                log(f"    is {state}, not peer_review: no review added")
                continue
            plan = seed["reviews"].get(f"{author}/{code}", {})
            await review(assignment_id, plan, reviewers, apis[author])

        log("")
        log(f"{'submission':<14} {'state':<14} {'votes +/-':<10} comments  assignment")
        for (author, code), assignment_id in assignments.items():
            view = await apis[author].ok("GET", f"/assignments/{assignment_id}/answers")
            plus = sum(a["approvals"] for a in view["answers"])
            minus = sum(a["disapprovals"] for a in view["answers"])
            notes = sum(len(a["comments"]) for a in view["answers"])
            log(
                f"{author + '/' + code:<14} {view['state']:<14} {f'{plus}/{minus}':<10} "
                f"{notes:<9} {assignment_id}"
            )
        log("")
        for key, user in users.items():
            log(f"{key:<8} {user.pseudonym:<10} {accounts[key]['email']}")
    finally:
        for api in apis.values():
            await api.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--password-env", default="SEED_PASSWORD")
    parser.add_argument(
        "--no-run-jobs", action="store_true", help="wait for a running worker instead"
    )
    asyncio.run(main(parser.parse_args()))
    sys.exit(0)
