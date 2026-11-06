"""What migration 0003 leaves behind: the RAG tables in `chips` and the pipeline's own tables."""

from sqlalchemy import text

from app.core.db import session_factory

CHIPS_TABLES = {
    "experts",
    "vignettes",
    "elicitation_sessions",
    "cue_keys",
    "highlights",
    "answer_sentences",
    "finding_units",
    "finding_unit_sentences",
    "unit_cues",
    "review_events",
}


async def _columns(schema: str, table: str) -> dict[str, str]:
    async with session_factory()() as db:
        rows = await db.execute(
            text(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = :t"
            ),
            {"s": schema, "t": table},
        )
        return {name: nullable for name, nullable in rows}


async def test_the_rag_tables_exist_in_chips():
    async with session_factory()() as db:
        found = set(
            await db.scalars(
                text(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'chips'"
                )
            )
        )
    assert found >= CHIPS_TABLES


async def test_units_know_what_they_embed():
    columns = await _columns("app", "knowledge_units")
    for name in (
        "kind",
        "highlight_id",
        "direction",
        "patient_words",
        "sentence_ids",
        "context",
        "embed_text",
        "embed_text_combined",
    ):
        assert columns.get(name) == "YES", name


async def test_findings_are_kept_apart_from_the_frozen_submission():
    columns = await _columns("app", "answer_findings")
    assert {"assignment_id", "record", "version", "check_outcome", "classifier"} <= set(columns)


async def test_the_system_can_ask_for_a_review():
    assert (await _columns("app", "review_requests"))["requested_by"] == "YES"


async def test_units_know_their_review_round_and_no_longer_a_question():
    columns = await _columns("app", "knowledge_units")
    assert columns["review_round"] == "NO"
    assert "question_id" not in columns, "left over from the verbatim stub"


async def test_assignments_count_their_review_rounds():
    assert (await _columns("app", "assignments"))["review_round"] == "NO"
