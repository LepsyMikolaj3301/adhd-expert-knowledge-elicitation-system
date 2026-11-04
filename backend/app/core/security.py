"""Password hashing and opaque tokens. Only hashes of tokens are stored."""

import asyncio
import hashlib
import secrets
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()
# Verified when the account can't log in, so that response time doesn't reveal which emails exist.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


# Each call costs tens of milliseconds of CPU and 64 MiB. A small pool keeps a flood of logins from
# stopping the event loop or using up the machine's memory: extra calls wait their turn.
_hash_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="argon2")


async def run_hash[T](function: Callable[..., T], *args: object) -> T:
    """Run a password function without blocking the other requests."""
    return await asyncio.get_running_loop().run_in_executor(_hash_pool, function, *args)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
