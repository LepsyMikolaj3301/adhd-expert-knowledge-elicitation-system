"""Which units a search may return."""

from typing import Any

from psycopg import sql
from pydantic import BaseModel, Field


class ExpertFilter(BaseModel):
    """Narrow a search. Every field that is set must hold.

    `include_synthetic` is False by default: units from synthetic experts (test data) must not
    reach a production answer. A development app over synthetic data sets it to True.
    """

    populations: list[str] | None = None  # adult | child ...
    tracks: list[str] | None = None
    framings: list[str] | None = None  # email | forum_post | personal_journal
    vignettes: list[str] | None = None  # only these vignette ids (codes)
    exclude_vignettes: list[str] = Field(default_factory=list)  # e.g. the case being read now
    experts: list[str] | None = None  # only these experts; cue keys are shared, so not filtered
    include_synthetic: bool = False

    def on_unit(self, alias: str = "u") -> tuple[list[sql.Composable], dict[str, Any]]:
        """Conditions on a `finding_units` row aliased `alias`, and their parameters."""
        a = sql.Identifier(alias)
        conditions: list[sql.Composable] = []
        params: dict[str, Any] = {}
        for column, name, values in (
            ("population", "f_populations", self.populations),
            ("track", "f_tracks", self.tracks),
            ("framing", "f_framings", self.framings),
            ("vignette_id", "f_vignettes", self.vignettes),
            ("expert_id", "f_experts", self.experts),
        ):
            if values is not None:
                conditions.append(
                    sql.SQL("{}.{} = ANY({})").format(
                        a, sql.Identifier(column), sql.Placeholder(name)
                    )
                )
                params[name] = list(values)
        if self.exclude_vignettes:
            conditions.append(sql.SQL("{}.vignette_id <> ALL(%(f_exclude)s)").format(a))
            params["f_exclude"] = list(self.exclude_vignettes)
        if not self.include_synthetic:
            conditions.append(sql.SQL("NOT {}.is_synthetic").format(a))
        return conditions, params

    def on_cue(self, alias: str = "c") -> tuple[list[sql.Composable], dict[str, Any]]:
        """The conditions a `cue_keys` row can answer by itself (its vignette)."""
        a = sql.Identifier(alias)
        conditions: list[sql.Composable] = []
        params: dict[str, Any] = {}
        if self.vignettes is not None:
            conditions.append(sql.SQL("{}.vignette_id = ANY(%(f_vignettes)s)").format(a))
            params["f_vignettes"] = list(self.vignettes)
        if self.exclude_vignettes:
            conditions.append(sql.SQL("{}.vignette_id <> ALL(%(f_exclude)s)").format(a))
            params["f_exclude"] = list(self.exclude_vignettes)
        return conditions, params


def all_of(conditions: list[sql.Composable]) -> sql.Composable:
    return sql.SQL(" AND ").join(conditions) if conditions else sql.SQL("TRUE")
