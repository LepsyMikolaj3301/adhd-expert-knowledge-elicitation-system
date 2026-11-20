"""Where experts agree, stored: groups of overlapping highlights in `chips.fragment_groups`.

Derived data. The highlights are the source of truth; a group is recomputed from them for one
version of a vignette, in the transaction that changes them (ingestion, removal), under the same
lock, so that nobody reads a count that includes an expert who was just withdrawn. The grouping and
the labels are expert_knowledge_core.agreement; this module only reads and writes the rows.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from expert_knowledge_core.agreement import (
    IOU_THRESHOLD,
    RULE_VERSION,
    Mark,
    agreement_groups,
)


async def recompute(db: AsyncSession, vignette_id: str, version: int) -> int:
    """Rebuilds the groups of one vignette version from the highlights now in `chips`. Returns how
    many groups there are. A version nobody has answered any more ends up with none."""
    key = {"vid": vignette_id, "ver": version}
    await db.execute(
        text(
            "DELETE FROM chips.fragment_groups WHERE vignette_id = :vid AND vignette_version = :ver"
        ),
        key,
    )
    n_answered = await db.scalar(
        text(
            "SELECT count(DISTINCT expert_id) FROM chips.finding_units "
            "WHERE vignette_id = :vid AND vignette_version = :ver"
        ),
        key,
    )
    rows = (
        await db.execute(
            text(
                "SELECT h.id, s.expert_id, lower(h.span) AS a, upper(h.span) AS b, h.direction "
                "FROM chips.highlights h JOIN chips.elicitation_sessions s ON s.id = h.session_id "
                "WHERE h.vignette_id = :vid AND h.vignette_version = :ver AND h.origin = 'expert'"
            ),
            key,
        )
    ).all()
    marks = [Mark(r.id, r.expert_id, (r.a, r.b), r.direction) for r in rows]
    groups = agreement_groups(marks, n_answered or 0, IOU_THRESHOLD)
    for members, a in groups:
        group_id = await db.scalar(
            text(
                "INSERT INTO chips.fragment_groups (vignette_id, vignette_version, span, "
                "n_answered, n_attending, n_toward, n_away, n_neutral, n_unclear, n_mixed, "
                "label, rule_version) VALUES (:vid, :ver, int4range(:a, :b), :n, :k, :toward, "
                ":away, :neutral, :unclear, :mixed, :label, :rule) RETURNING id"
            ),
            {
                **key, "a": a.span[0], "b": a.span[1], "n": a.n, "k": a.k,
                "toward": a.counts.get("toward", 0), "away": a.counts.get("away", 0),
                "neutral": a.counts.get("neutral", 0), "unclear": a.counts.get("unclear", 0),
                "mixed": a.counts.get("mixed", 0), "label": a.label, "rule": RULE_VERSION,
            },
        )  # fmt: skip
        await db.execute(
            text(
                "INSERT INTO chips.fragment_group_members (group_id, highlight_id, expert_id) "
                "VALUES (:g, :h, :e)"
            ),
            [{"g": group_id, "h": m.id, "e": m.expert} for m in members],
        )
    return len(groups)


async def recompute_all(db: AsyncSession) -> int:
    """Every vignette version that has highlights, for the backfill. Returns the groups written."""
    versions = (
        await db.execute(
            text("SELECT DISTINCT vignette_id, vignette_version FROM chips.highlights")
        )
    ).all()
    # Versions that lost all their highlights keep no groups: clear what is left over first.
    await db.execute(
        text(
            "DELETE FROM chips.fragment_groups g WHERE NOT EXISTS "
            "(SELECT 1 FROM chips.highlights h "
            "WHERE h.vignette_id = g.vignette_id AND h.vignette_version = g.vignette_version)"
        )
    )
    return sum([await recompute(db, vid, ver) for vid, ver in versions])
