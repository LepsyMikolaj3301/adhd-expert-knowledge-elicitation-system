"""Typed model of config/sources.yaml (the corpus source manifest)."""

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    # Reject unknown keys so a typo in the YAML fails on load instead of mid-download.
    model_config = ConfigDict(extra="forbid")


class HttpAttempt(Model):
    kind: Literal["http"]
    expect: Literal["pdf", "xml", "html", "json"]
    # Saved as <name>.<ext>; only used with `url`, `urls` supplies its own names.
    name: str = "source"
    url: str | None = None
    urls: dict[str, str] | None = None

    @model_validator(mode="after")
    def _one_of_url_urls(self) -> "HttpAttempt":
        if (self.url is None) == (self.urls is None):
            raise ValueError("exactly one of `url` or `urls` is required")
        return self

    def targets(self) -> dict[str, str]:
        """File name -> URL; every target must download for the attempt to succeed."""
        return self.urls or {self.name: self.url or ""}


class EuropePmcAttempt(Model):
    kind: Literal["europepmc_resolve"]
    # Europe PMC search query; if the hit has a PMCID its fullTextXML is fetched.
    query: str


Attempt = Annotated[HttpAttempt | EuropePmcAttempt, Field(discriminator="kind")]


class Manual(Model):
    # Not downloaded: the first existing path is copied into data/raw/<id>/.
    paths: list[str]


class Auth(Model):
    type: Literal["oauth2_client_credentials"]
    token_url: str
    scope: str
    env: list[str]
    token_ttl_minutes: int


class Metadata(Model):
    """Descriptive fields copied into meta.json; downstream stages read them from there."""

    role: str
    licence: str | None = None
    citation: str | None = None
    evidence_level: str | None = None
    population: str | None = None


class Source(Model):
    id: str
    title: str
    doi: str | None = None
    pmid: str | None = None
    pmcid: str | None = None
    release_or_version: str | None = None
    metadata: Metadata

    # Exactly one way to obtain the source:
    attempts: list[Attempt] | None = None  # downloaded, tried in order
    manual: Manual | None = None  # placed by hand
    auth: Auth | None = None  # API behind credentials

    # Only for API sources.
    required_headers: dict[str, str] | None = None
    endpoints: dict[str, str] | None = None

    @model_validator(mode="after")
    def _one_acquisition_method(self) -> "Source":
        methods = [self.attempts, self.manual, self.auth]
        if sum(m is not None for m in methods) != 1:
            raise ValueError(f"{self.id}: exactly one of attempts, manual, auth is required")
        return self

    @property
    def needs_credentials(self) -> bool:
        return self.auth is not None


class Excluded(Model):
    id: str | None = None  # source id; set when the source was once fetched, so stages skip it
    name: str
    reason: str


class Manifest(Model):
    sources: list[Source]
    excluded: list[Excluded] = []

    @model_validator(mode="after")
    def _consistent_ids(self) -> "Manifest":
        ids = [s.id for s in self.sources]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate source ids")
        if clash := set(ids) & self.excluded_ids:
            raise ValueError(f"ids both in sources and excluded: {sorted(clash)}")
        return self

    @property
    def excluded_ids(self) -> set[str]:
        return {e.id for e in self.excluded if e.id}


def load_manifest(path: Path) -> Manifest:
    return Manifest.model_validate(yaml.safe_load(path.read_text()))


def excluded_source_ids(path: Path = Path("config/sources.yaml")) -> set[str]:
    """Source ids that must never enter the pipeline (stale copies may linger on disk / in S3)."""
    return load_manifest(path).excluded_ids
