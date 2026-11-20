"""Operator commands.

python -m app.cli create-admin --email a@example.com --name "Ada"   (asks for the password)
python -m app.cli export-openapi --out ../frontend/openapi.json
python -m app.cli import-vignettes --dir DIR --whatifs FILE --admin-email a@example.com
    Loads the V*.json files in DIR as drafts, with the what-ifs from FILE ({"V001": "..."}).
    All or nothing; codes that already exist are skipped. Drafts still have to be published.
python -m app.cli recompute-agreement
    Rebuilds the groups of experts who marked the same passage (chips.fragment_groups) for every
    vignette version. Ingestion and removal keep them up to date; this fills in older data.
"""

import argparse
import asyncio
import getpass
import json
import sys
from pathlib import Path

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select, text

from app.auth.schemas import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from app.core.db import session_factory
from app.core.errors import DomainError, invalid
from app.knowledge.agreement import recompute_all
from app.knowledge.ingest import BM25_LOCK
from app.main import create_app
from app.users.models import Role, User
from app.users.service import create_user
from app.vignettes.importing import ImportResult, import_vignettes, read_whatifs


async def _create_admin(email: str, name: str, password: str) -> str:
    async with session_factory()() as db:
        user = await create_user(
            db, email=email, display_name=name, role=Role.ADMIN, password=password
        )
        await db.commit()
        return user.pseudonym


async def _import_vignettes(directory: Path, whatifs_file: Path, email: str) -> ImportResult:
    whatifs = read_whatifs(whatifs_file)
    async with session_factory()() as db:
        admin = await db.scalar(select(User).where(User.email == email.strip().lower()))
        if admin is None or admin.role != Role.ADMIN or not admin.is_active:
            raise invalid("not_an_admin", f"{email} isn't an active admin account.")
        result = await import_vignettes(db, directory, whatifs, admin)
        await db.commit()
        return result


async def _recompute_agreement() -> int:
    async with session_factory()() as db:
        # The lock of ingestion and removal: nobody changes the highlights while we count them.
        await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": BM25_LOCK})
        groups = await recompute_all(db)
        await db.commit()
        return groups


def openapi_json() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


def _run_import(args: argparse.Namespace) -> int:
    try:
        result = asyncio.run(_import_vignettes(args.dir, args.whatifs, args.admin_email))
    except DomainError as exc:
        print(exc.message, file=sys.stderr)
        return 1
    print(f"Created {len(result.created)} draft vignettes: {', '.join(result.created) or '-'}")
    if result.skipped:
        print(f"Skipped {len(result.skipped)} that already exist: {', '.join(result.skipped)}")
    return 0


def _run_create_admin(args: argparse.Namespace) -> int:
    # The same rules as logging in: an account that passes here must be able to log in.
    try:
        email = TypeAdapter(EmailStr).validate_python(args.email)
    except ValidationError:
        print(
            f"The email {args.email!r} isn't accepted at login. "
            "Reserved domains such as .local and .test are refused too.",
            file=sys.stderr,
        )
        return 1
    password = getpass.getpass("Password: ")
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        print(
            f"The password needs {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters.",
            file=sys.stderr,
        )
        return 1
    try:
        pseudonym = asyncio.run(_create_admin(email, args.name, password))
    except DomainError as exc:
        print(exc.message, file=sys.stderr)
        return 1
    print(f"Created admin {pseudonym}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    openapi = commands.add_parser("export-openapi")
    openapi.add_argument("--out", type=Path, required=True)
    importing = commands.add_parser("import-vignettes")
    importing.add_argument("--dir", type=Path, required=True)
    importing.add_argument("--whatifs", type=Path, required=True)
    importing.add_argument("--admin-email", required=True)
    commands.add_parser("recompute-agreement")
    args = parser.parse_args(argv)

    if args.command == "export-openapi":
        args.out.write_text(openapi_json())
        return 0
    if args.command == "import-vignettes":
        return _run_import(args)
    if args.command == "recompute-agreement":
        print(f"{asyncio.run(_recompute_agreement())} groups")
        return 0
    return _run_create_admin(args)


if __name__ == "__main__":
    raise SystemExit(main())
