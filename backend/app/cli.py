"""Operator commands.

python -m app.cli create-admin --email a@example.com --name "Ada"   (asks for the password)
python -m app.cli export-openapi --out ../frontend/openapi.json
"""

import argparse
import asyncio
import getpass
import json
import sys
from pathlib import Path

from pydantic import EmailStr, TypeAdapter, ValidationError

from app.auth.schemas import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from app.core.db import session_factory
from app.core.errors import DomainError
from app.main import create_app
from app.users.models import Role
from app.users.service import create_user


async def _create_admin(email: str, name: str, password: str) -> str:
    async with session_factory()() as db:
        user = await create_user(
            db, email=email, display_name=name, role=Role.ADMIN, password=password
        )
        await db.commit()
        return user.pseudonym


def openapi_json() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    admin = commands.add_parser("create-admin")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", required=True)
    openapi = commands.add_parser("export-openapi")
    openapi.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "export-openapi":
        args.out.write_text(openapi_json())
        return 0

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


if __name__ == "__main__":
    raise SystemExit(main())
