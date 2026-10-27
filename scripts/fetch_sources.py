"""Download the corpus sources listed in config/sources.yaml into data/raw/<id>/.

Usage: python scripts/fetch_sources.py [--manifest config/sources.yaml] [--out data/raw]
                                       [--only ID ...] [--force]

Each source's `attempts` are tried in order; the first one whose response passes its `expect`
check is saved unmodified next to a meta.json. Sources whose saved files still match the sha256
in meta.json are skipped unless --force is given. ICD-API sources need ICD_CLIENT_ID and
ICD_CLIENT_SECRET (read from the environment or .env) and are skipped without them; `manual`
sources are copied from data/manual/. The manifest is validated against app.sources.Manifest
on load. Set CONTACT_EMAIL so the User-Agent carries a contact address.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv

from app.sources import EuropePmcAttempt, HttpAttempt, Source, load_manifest

EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest"
EXTENSIONS = {"pdf": ".pdf", "xml": ".xml", "html": ".html", "json": ".json"}
CONTENT_TYPES = {".pdf": "application/pdf", ".html": "text/html", ".xml": "application/xml"}
BLOCK_PAGE = re.compile(rb"<title[^>]*>[^<]*(captcha|checking your browser|just a moment)", re.I)
RETRY_STATUSES = {429, 500, 502, 503, 504}
MIN_INTERVAL = 1.0  # seconds between requests to the same host
# Section headings of the ICD-11 CDDR diagnostic requirements; the MMS entity is checked for
# them (logged, never enforced) since it is the only ICD text indexed.
CDDR_SECTIONS = [
    "Essential (Required) Features",
    "Additional Clinical Features",
    "Boundary with Normality",
    "Course Features",
    "Developmental Presentations",
    "Culture-Related Features",
    "Sex- and/or Gender-Related Features",
    "Boundaries with Other Disorders and Conditions",
]


class AttemptFailed(Exception):
    pass


@dataclass
class Download:
    name: str
    body: bytes
    record: dict


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class PoliteClient:
    """httpx client with a per-host rate limit (applied to redirects too) and retries."""

    def __init__(self, contact: str | None) -> None:
        user_agent = "adhd-kb-pipeline/0.1" + (f" (mailto:{contact})" if contact else "")
        self._last_request: dict[str, float] = {}
        self._client = httpx.Client(
            follow_redirects=True,
            timeout=120,
            headers={"User-Agent": user_agent},
            event_hooks={"request": [self._throttle]},
        )

    def _throttle(self, request: httpx.Request) -> None:
        host = request.url.host
        wait = self._last_request.get(host, 0.0) + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_request[host] = time.monotonic()

    def post_form(self, url: str, data: dict[str, str]) -> httpx.Response:
        try:
            response = self._client.post(url, data=data)
        except httpx.TransportError as e:
            raise AttemptFailed(type(e).__name__) from e
        if not response.is_success:
            raise AttemptFailed(f"HTTP {response.status_code} from {url}")
        return response

    def get(
        self, url: str, headers: dict[str, str] | None = None, retries: int = 4
    ) -> httpx.Response:
        for attempt in range(retries + 1):
            try:
                response = self._client.get(url, headers=headers)
            except httpx.TransportError as e:
                if attempt == retries:
                    raise AttemptFailed(f"{type(e).__name__}: {e}") from e
            else:
                if response.status_code not in RETRY_STATUSES or attempt == retries:
                    return response
            time.sleep(2**attempt)
        raise AssertionError("unreachable")


def check_body(body: bytes, expect: str) -> None:
    if expect == "pdf":
        ok = body.startswith(b"%PDF")
    elif expect == "xml":
        ok = b"<article" in body
    elif expect == "html":
        ok = b"<html" in body[:4096].lower() and not BLOCK_PAGE.search(body)
    elif expect == "json":
        try:
            json.loads(body)
            ok = True
        except ValueError:
            ok = False
    else:
        raise ValueError(f"unknown expect: {expect}")
    if not ok:
        raise AttemptFailed(f"body is not valid {expect} (or is a bot-check page)")


def fetch(
    client: PoliteClient,
    url: str,
    expect: str,
    name: str,
    headers: dict[str, str] | None = None,
) -> Download:
    response = client.get(url, headers)
    if not response.is_success:
        raise AttemptFailed(f"HTTP {response.status_code} from {url}")
    body = response.content
    check_body(body, expect)
    filename = name + EXTENSIONS[expect]
    return Download(
        filename,
        body,
        {
            "name": filename,
            "url": url,
            "final_url": str(response.url),
            "retrieved_at": now(),
            "http_status": response.status_code,
            "sha256": sha256(body),
            "content_type": response.headers.get("content-type"),
        },
    )


def run_http(client: PoliteClient, attempt: HttpAttempt) -> tuple[list[Download], dict]:
    return [fetch(client, url, attempt.expect, name) for name, url in attempt.targets().items()], {}


def run_europepmc_resolve(
    client: PoliteClient, attempt: EuropePmcAttempt
) -> tuple[list[Download], dict]:
    query = urlencode({"query": attempt.query, "resultType": "core", "format": "json"})
    search = fetch(client, f"{EUROPEPMC}/search?{query}", "json", "europepmc_search")
    hits = json.loads(search.body)["resultList"]["result"]
    if not hits:
        raise AttemptFailed(f"no Europe PMC hit for {attempt.query}")
    hit = hits[0]
    info = {k: hit.get(k) for k in ("doi", "pmid", "pmcid", "isOpenAccess", "license")}
    if not hit.get("pmcid"):
        raise AttemptFailed(f"Europe PMC hit has no PMCID (isOpenAccess={hit.get('isOpenAccess')})")
    fulltext = fetch(client, f"{EUROPEPMC}/{hit['pmcid']}/fullTextXML", "xml", "fulltext")
    return [fulltext, search], {"europepmc": info}


class IcdSession:
    """WHO ICD-API calls with an OAuth2 client-credentials token, refreshed before it expires."""

    def __init__(self, client: PoliteClient, source: Source) -> None:
        assert source.auth and source.required_headers
        self._client = client
        self._auth = source.auth
        self._headers = source.required_headers
        self._token = ""
        self._expires = 0.0

    def missing_env(self) -> list[str]:
        return [name for name in self._auth.env if not os.environ.get(name)]

    def _access_token(self) -> str:
        if time.monotonic() >= self._expires:
            client_id, client_secret = (os.environ[name] for name in self._auth.env)
            response = self._client.post_form(
                self._auth.token_url,
                {
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "scope": self._auth.scope,
                },
            )
            self._token = response.json()["access_token"]
            self._expires = time.monotonic() + self._auth.token_ttl_minutes * 60
        return self._token

    def get(self, url: str, name: str) -> Download:
        headers = {**self._headers, "Authorization": f"Bearer {self._access_token()}"}
        return fetch(self._client, url, "json", name, headers)


def https(uri: str) -> str:
    """ICD-API returns http:// URIs; always call https://, without any query string."""
    return uri.replace("http://", "https://", 1).split("?")[0]


def run_icd_mms(session: IcdSession, source: Source) -> tuple[list[Download], dict]:
    endpoints = source.endpoints or {}
    releases = session.get(endpoints["list_releases"], "releases")
    lookup = session.get(endpoints["code_lookup"], "codeinfo")
    latest = json.loads(releases.body).get("latestRelease")
    root = https(json.loads(lookup.body)["stemId"])
    pinned = source.release_or_version
    if pinned and f"/{pinned}/" not in str(latest):
        print(f"    warning: latest ICD release is {latest}, manifest pins {pinned}")
    if root != https(endpoints["mms_entity"]):
        print(f"    warning: codeinfo stemId {root} differs from the manifest's mms_entity")

    entities: list[Download] = []
    queue, seen = [root], set()
    while queue:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        entity = session.get(f"{url}?include=diagnosticCriteria", "entity")
        body = json.loads(entity.body)
        code = body.get("code") or url.rstrip("/").rsplit("/", 1)[-1]
        entity.name = entity.record["name"] = re.sub(r"[^\w.-]", "_", code) + ".json"
        entities.append(entity)
        queue.extend(https(child) for child in body.get("child", []))

    for key in ("mms_residual_other", "mms_residual_unspecified"):
        if https(endpoints[key]) not in seen:
            print(f"    warning: {key} was not reached through the child links")
    root_body = json.loads(entities[0].body)
    text = criteria_text(root_body.get("diagnosticCriteria")).lower()
    present = [s for s in CDDR_SECTIONS if s.lower() in text]
    meta = {
        "icd": {
            "latest_release": latest,
            "entity_uris": sorted(seen),
            "diagnostic_criteria_in_mms": bool(root_body.get("diagnosticCriteria")),
            "cddr_sections_present": present,
            "cddr_sections_missing": [s for s in CDDR_SECTIONS if s not in present],
        }
    }
    return [releases, lookup, *entities], meta


def criteria_text(value: object) -> str:
    """diagnosticCriteria arrives as a string or a {"@language", "@value"} object (Markdown)."""
    if isinstance(value, dict):
        value = value.get("@value", "")
    return value if isinstance(value, str) else ""


def process_icd(sessions: dict[str, IcdSession], source: Source, out_root: Path) -> dict:
    session = sessions[source.id]
    if missing := session.missing_env():
        return {"status": "SKIPPED", "detail": f"set {', '.join(missing)} (env or .env)"}
    try:
        downloads, meta = run_icd_mms(session, source)
    except AttemptFailed as e:
        return {"status": "FAILED", "detail": str(e)}
    save(source, out_root / source.id, downloads, meta)
    if missing_sections := meta["icd"].get("cddr_sections_missing"):
        print(f"    warning: CDDR sections missing from the MMS criteria: {missing_sections}")
    return {"status": "OK", "detail": ", ".join(d.name for d in downloads)}


def is_cached(out_dir: Path) -> bool:
    meta_path = out_dir / "meta.json"
    if not meta_path.exists():
        return False
    files = json.loads(meta_path.read_text())["files"]
    return all(
        (out_dir / f["name"]).is_file()
        and sha256((out_dir / f["name"]).read_bytes()) == f["sha256"]
        for f in files
    )


def save(source: Source, out_dir: Path, downloads: list[Download], meta: dict) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    for download in downloads:
        (out_dir / download.name).write_bytes(download.body)
    meta = {
        "source_id": source.id,
        "title": source.title,
        "release_or_version": source.release_or_version,
        **source.model_dump(include={"doi", "pmid", "pmcid"}, exclude_none=True),
        "metadata": source.metadata.model_dump(exclude_none=True),
        **meta,
        "files": [d.record for d in downloads],
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")


def fetch_manual(paths: list[str]) -> tuple[list[Download], dict] | None:
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_file():
            body = path.read_bytes()
            record = {
                "name": "source" + path.suffix,
                "url": f"manual://{path.as_posix()}",
                "retrieved_at": now(),
                "http_status": None,
                "sha256": sha256(body),
                "content_type": CONTENT_TYPES.get(path.suffix),
            }
            return [Download(record["name"], body, record)], {"attempt_kind": "manual"}
    return None


def process(
    client: PoliteClient,
    sessions: dict[str, IcdSession],
    source: Source,
    out_root: Path,
    force: bool,
) -> dict:
    out_dir = out_root / source.id
    if not force and is_cached(out_dir):
        return {"status": "CACHED", "detail": str(out_dir)}
    if source.needs_credentials:
        return process_icd(sessions, source, out_root)

    if source.manual:
        paths = source.manual.paths
        result = fetch_manual(paths)
        if result is None:
            return {"status": "MISSING", "detail": f"place file at one of {paths}"}
        save(source, out_dir, *result)
        return {"status": "OK", "detail": "copied from data/manual/"}

    errors = []
    for index, attempt in enumerate(source.attempts or []):
        try:
            if isinstance(attempt, HttpAttempt):
                downloads, extra = run_http(client, attempt)
            else:
                downloads, extra = run_europepmc_resolve(client, attempt)
        except AttemptFailed as e:
            print(f"    attempt {index} ({attempt.kind}) failed: {e}")
            errors.append(f"attempt {index}: {e}")
            continue
        meta = {"attempt_index": index, "attempt_kind": attempt.kind, **extra}
        save(source, out_dir, downloads, meta)
        status = "OK" if index == 0 else "OK (fallback)"
        return {
            "status": status,
            "attempt_index": index,
            "detail": ", ".join(f"{d.name} {d.record['sha256'][:12]}" for d in downloads),
        }
    return {"status": "FAILED", "detail": "; ".join(errors)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=Path("config/sources.yaml"))
    parser.add_argument("--out", type=Path, default=Path("data/raw"))
    parser.add_argument("--only", nargs="+", metavar="ID", help="fetch only these source ids")
    parser.add_argument("--force", action="store_true", help="re-download cached sources")
    args = parser.parse_args()

    load_dotenv()
    all_sources = sources = load_manifest(args.manifest).sources
    if args.only:
        unknown = set(args.only) - {s.id for s in sources}
        if unknown:
            raise SystemExit(f"Unknown source ids: {', '.join(sorted(unknown))}")
        sources = [s for s in sources if s.id in args.only]

    contact = os.environ.get("CONTACT_EMAIL")
    if not contact:
        print("warning: CONTACT_EMAIL is not set; User-Agent has no contact address")
    client = PoliteClient(contact)
    sessions = {s.id: IcdSession(client, s) for s in all_sources if s.auth}

    report = []
    for source in sources:
        print(source.id)
        result = {"source_id": source.id, **process(client, sessions, source, args.out, args.force)}
        print(f"    {result['status']}: {result['detail']}")
        report.append(result)

    # Merge into the previous report so an --only run doesn't drop the other sources.
    report_path = args.out / "_fetch_report.json"
    previous = json.loads(report_path.read_text())["sources"] if report_path.exists() else []
    known = {s.id for s in all_sources}
    merged = {r["source_id"]: r for r in previous if r["source_id"] in known}
    merged |= {r["source_id"]: r for r in report}
    args.out.mkdir(parents=True, exist_ok=True)
    report_doc = {
        "generated_at": now(),
        "manifest": str(args.manifest),
        "sources": list(merged.values()),
    }
    report_path.write_text(json.dumps(report_doc, indent=2) + "\n")

    print("\nSummary")
    for r in report:
        print(f"  {r['source_id']:<48} {r['status']}")
    if any(r["status"] == "FAILED" for r in report):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
