"""One error shape for the whole API: {code, message, details}. `code` is stable; show `message`."""

import logging
import traceback
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger(__name__)


class ErrorResponse(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class DomainError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_409_CONFLICT,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def not_found(what: str = "Resource") -> DomainError:
    return DomainError("not_found", f"{what} not found.", status.HTTP_404_NOT_FOUND)


def invalid(code: str, message: str, details: dict[str, Any] | None = None) -> DomainError:
    return DomainError(code, message, status.HTTP_422_UNPROCESSABLE_CONTENT, details)


def forbidden(message: str = "You may not do this.") -> DomainError:
    return DomainError("forbidden", message, status.HTTP_403_FORBIDDEN)


def safe_traceback(exc: BaseException) -> str:
    """The stack and the error types, without any error message.

    Messages can quote expert text: Postgres adds "Failing row contains (...)" to its own errors,
    and it comes along in the exception chain, whatever SQLAlchemy hides.
    """
    lines: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        lines += traceback.format_tb(current.__traceback__)
        lines.append(f"{type(current).__module__}.{type(current).__qualname__}\n")
        current = current.__cause__ or current.__context__
    return "".join(lines)


def _response(
    status_code: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    body = ErrorResponse(code=code, message=message, details=details)
    return JSONResponse(status_code=status_code, content=body.model_dump())


class SafeErrorMiddleware:
    """Answers unexpected errors and logs them safely.

    Not an exception handler: Starlette re-raises after those, and the server then logs the full
    exception chain, messages included.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            started = started or message["type"] == "http.response.start"
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            logger.error("unhandled error\n%s", safe_traceback(exc))
            if not started:
                response = _response(
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    "internal_error",
                    "Something went wrong.",
                )
                await response(scope, receive, send)


def install_error_handlers(app: FastAPI) -> None:
    app.add_middleware(SafeErrorMiddleware)

    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError) -> JSONResponse:
        return _response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        # Only location and reason: pydantic's `input` would echo passwords and answers.
        errors = [
            {"loc": list(error["loc"]), "type": error["type"], "msg": error["msg"]}
            for error in exc.errors()
        ]
        return _response(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "validation_error",
            "The request is not valid.",
            {"errors": errors},
        )

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException) -> JSONResponse:
        return _response(exc.status_code, "http_error", str(exc.detail))
