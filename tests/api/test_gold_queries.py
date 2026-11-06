"""infra/gold.sh holds the SQL that exports the answers. It runs against a production copy once in a
while, so a renamed column would break it exactly when it is needed: run its queries here."""

import json
import re
from pathlib import Path

from api_helpers import (
    FULL_PAYLOAD,
    GATE_ANSWERS,
    admin_api,
    answer_and_submit,
    assign,
    expert_api,
    published_version,
    save,
)
from sqlalchemy import text

from app.core.db import session_factory

SCRIPT = (Path(__file__).resolve().parents[2] / "infra" / "gold.sh").read_text()


def script_sql(name: str) -> str:
    match = re.search(rf"read -r -d '' {name} <<'SQL' \|\| true\n(.*?)\nSQL\n", SCRIPT, re.S)
    assert match, f"{name} not found in infra/gold.sh"
    return match.group(1)


async def rows(name: str) -> list[str]:
    """What `psql -At` would print, one string per row (the driver would decode a json column)."""
    sql = script_sql(name)
    if name != "COUNTS_SQL":
        sql = f"SELECT q.row_to_json::text FROM ({sql}) q"
    async with session_factory()() as db:
        return [r[0] for r in await db.execute(text(sql))]


async def test_the_export_queries_return_the_raw_answers_one_json_object_per_line():
    admin = await admin_api()
    done, working = await expert_api("done@example.com"), await expert_api("working@example.com")
    version = await published_version(admin)
    done_id, working_id = await assign(admin, version, done, working)
    await answer_and_submit(done, done_id)
    await working.ok("POST", f"/assignments/{working_id}/start")
    await save(working, working_id, {"answers": GATE_ANSWERS})

    [line] = await rows("SUBMISSIONS_SQL")
    # No newline may survive in a line: the file has one case per line.
    assert "\n" not in line
    submission = json.loads(line)
    assert submission["assignment_id"] == done_id
    assert submission["payload"]["answers"] == FULL_PAYLOAD["answers"]
    assert submission["payload"]["expert_pseudonym"] == done.pseudonym
    # The joined vignette is the one the answers were given to.
    assert submission["vignette_code"] == submission["payload"]["vignette_code"]
    assert submission["vignette_hash"] and submission["vignette_text"]
    # The vignette's hidden design never leaves in the answers file.
    assert "design" not in submission

    [draft_line] = await rows("DRAFTS_SQL")
    draft = json.loads(draft_line)
    assert draft["assignment_id"] == working_id
    assert draft["expert_pseudonym"] == working.pseudonym
    assert draft["payload"]["answers"] == GATE_ANSWERS


async def test_the_counts_query_lists_every_table_of_both_schemas():
    names = {line.rsplit(" ", 1)[0] for line in await rows("COUNTS_SQL")}
    assert {"app.submissions", "app.users", "app.alembic_version", "chips.highlights"} <= names
    assert all(n.startswith(("app.", "chips.")) for n in names)
