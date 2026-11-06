"""Clients per user and shortcuts that walk an assignment through the workflow."""

from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import update

from app.core.db import session_factory
from app.jobs.worker import run_once
from app.main import app
from app.users.models import Role
from app.users.service import create_user
from app.vignettes.models import VignetteVersion

PASSWORD = "correct horse battery"
CUE = "I reorganised my entire desk instead of starting the report"
CONFOUNDER = "I have barely slept since the move"
FILLER = " ".join(f"word{i}" for i in range(130))
VIGNETTE_TEXT = f"{CUE} and then {CONFOUNDER}. {FILLER}"
DESIGN_SECRET = "planted-design-secret"
WHATIF = "the-whatif-secret happened earlier that day"

_counter = {"n": 0}


def vignette_body(code: str | None = None, **overrides: Any) -> dict[str, Any]:
    _counter["n"] += 1
    body: dict[str, Any] = {
        "code": code or f"V{_counter['n'] + 100:03d}",
        "text": VIGNETTE_TEXT,
        "framing": "personal_journal",
        "q4_whatif": WHATIF,
        "design": {
            "purpose": DESIGN_SECRET,
            "planted_cues": [{"quote": CUE, "trait": "task avoidance", "strength": "moderate"}],
            "confounders": [{"quote": CONFOUNDER, "alternative_explanation": "sleep loss"}],
        },
    }
    body.update(overrides)
    return body


class Api:
    """An HTTP client with its own cookie jar: one per logged-in user."""

    def __init__(self, user_id: str | None = None, pseudonym: str | None = None) -> None:
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test/api/v1"
        )
        self.user_id = user_id
        self.pseudonym = pseudonym

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return await self.client.request(method, path, **kwargs)

    async def ok(self, method: str, path: str, expected: int = 200, **kwargs: Any) -> Any:
        response = await self.request(method, path, **kwargs)
        assert response.status_code == expected, f"{method} {path}: {response.text}"
        return response.json() if response.content else None

    async def fails(self, method: str, path: str, status: int, code: str, **kwargs: Any) -> dict:
        response = await self.request(method, path, **kwargs)
        assert response.status_code == status, f"{method} {path}: {response.text}"
        body = response.json()
        assert body["code"] == code, body
        assert set(body) == {"code", "message", "details"}
        return body

    async def close(self) -> None:
        await self.client.aclose()


async def login_as(role: Role, email: str, *, is_synthetic: bool = False) -> Api:
    async with session_factory()() as db:
        user = await create_user(
            db,
            email=email,
            display_name=email.split("@")[0],
            role=role,
            password=PASSWORD,
            is_synthetic=is_synthetic,
        )
        await db.commit()
    api = Api(str(user.id), user.pseudonym)
    await api.ok("POST", "/auth/login", json={"email": email, "password": PASSWORD})
    return api


async def admin_api(email: str = "admin@example.com") -> Api:
    return await login_as(Role.ADMIN, email)


async def expert_api(email: str, *, is_synthetic: bool = False) -> Api:
    return await login_as(Role.EXPERT, email, is_synthetic=is_synthetic)


async def set_stored_questions(version_id: str, question_ids: list[str]) -> None:
    """The API always asks Q1-Q6, but rows stored earlier may hold fewer: simulate one."""
    async with session_factory()() as db:
        await db.execute(
            update(VignetteVersion)
            .where(VignetteVersion.id == UUID(version_id))
            .values(question_ids=question_ids)
        )
        await db.commit()


async def published_version(
    admin: Api, question_ids: list[str] | None = None, **overrides: Any
) -> dict[str, Any]:
    vignette = await admin.ok("POST", "/vignettes", 201, json=vignette_body(**overrides))
    version = vignette["versions"][0]
    if question_ids is not None:
        await set_stored_questions(version["id"], question_ids)
    return await admin.ok("POST", f"/vignette-versions/{version['id']}/publish")


async def assign(admin: Api, version: dict[str, Any], *experts: Api) -> list[str]:
    created = await admin.ok(
        "POST",
        f"/vignette-versions/{version['id']}/assignments",
        201,
        json={"expert_ids": [expert.user_id for expert in experts]},
    )
    return [assignment["id"] for assignment in created]


GATE_ANSWERS = {
    "Q1": f'"{CUE}" reads as avoidance of the task rather than ordinary tidiness.',
    "Q2": "Could equally be sleep loss after the recent move, not a trait.",
    "Q3": "Longitudinal history, childhood onset and how other life domains are affected.",
}
Q5_ANSWER = "A junior clinician would over-read the desk story as a clear sign."
Q4_WHY = "the-q4-why-text explains the rush."
HYPOTHESIS = "the-hypothesis-text: tired, not trait-like"


def highlight(chip: int, quote: str = CUE, direction: str | None = "toward") -> dict[str, Any]:
    """A citation of `quote`, which must be in VIGNETTE_TEXT."""
    start = VIGNETTE_TEXT.index(quote)
    return {
        "chip": chip,
        "text": quote,
        "span": [start, start + len(quote)],
        "direction": direction,
    }


FULL_PAYLOAD = {
    "answers": {**GATE_ANSWERS, "Q4": Q4_WHY, "Q5": Q5_ANSWER},
    "highlights": [highlight(1)],
    "q4": {"hypothesis": HYPOTHESIS, "shift": 1, "toward": "less_adhd"},
    "rating": 2,
}


async def save(expert: Api, assignment_id: str, payload: dict[str, Any]) -> int:
    current = await expert.ok("GET", f"/assignments/{assignment_id}")
    saved = await expert.ok(
        "PUT",
        f"/assignments/{assignment_id}/draft",
        json={"version": current["draft"]["version"], "payload": payload},
    )
    return saved["version"]


async def answer_and_submit(
    expert: Api, assignment_id: str, payload: dict[str, Any] | None = None
) -> None:
    payload = payload if payload is not None else FULL_PAYLOAD
    await expert.ok("POST", f"/assignments/{assignment_id}/start")
    await save(expert, assignment_id, {"answers": GATE_ANSWERS})
    await expert.ok("POST", f"/assignments/{assignment_id}/pass-gate")
    await save(expert, assignment_id, payload)
    await expert.ok("POST", f"/assignments/{assignment_id}/submit")


async def run_jobs() -> int:
    count = 0
    while await run_once():
        count += 1
    return count


async def reach_review(admin: Api, *experts: Api) -> tuple[list[str], dict[str, Any]]:
    """Assign one published version to the experts, then take each one up to review."""
    version = await published_version(admin)
    ids = await assign(admin, version, *experts)
    for expert, assignment_id in zip(experts, ids, strict=True):
        await answer_and_submit(expert, assignment_id)
        await run_jobs()
        await expert.ok("POST", f"/assignments/{assignment_id}/expert-check/skip")
        await run_jobs()
    return ids, version


async def decide_all(api: Api, assignment_id: str, decision: str = "approve") -> Any:
    units = await api.ok("GET", f"/assignments/{assignment_id}/units")
    return await api.ok(
        "POST",
        f"/assignments/{assignment_id}/unit-decisions",
        json={"decisions": [{"unit_id": u["id"], "decision": decision} for u in units]},
    )


async def to_units(admin, expert, assignment_id, skip=False):
    """Carry a submitted assignment through processing and the check to its built units."""
    await run_jobs()
    verb = "skip" if skip else "complete"
    await (admin if skip else expert).ok(
        "POST", f"/assignments/{assignment_id}/expert-check/{verb}"
    )
    await run_jobs()


async def two_experts():
    """e1 and e2 have both finished, so both are in review and each can read the other's units."""
    admin = await admin_api()
    e1, e2 = await expert_api("e1@example.com"), await expert_api("e2@example.com")
    version = await published_version(admin)
    first, second = await assign(admin, version, e1, e2)
    await answer_and_submit(e1, first)
    await to_units(admin, e1, first, skip=True)
    await answer_and_submit(e2, second)
    await to_units(admin, e2, second)
    return admin, e1, e2, first, second
