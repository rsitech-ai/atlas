"""Starlette middleware for owner-token authenticated local IPC."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from rsi_atlas_security.ipc import load_ipc_token, tokens_match
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class IpcAuthMiddleware(BaseHTTPMiddleware):
    """Require Bearer token from owner-private token file when enabled."""

    def __init__(self, app: object, *, token_path: object, enabled: bool) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._token_path = token_path
        self._enabled = enabled

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not self._enabled:
            return await call_next(request)
        expected = load_ipc_token(self._token_path)  # type: ignore[arg-type]
        if expected is None:
            return JSONResponse(
                status_code=503,
                content={"detail": "IPC token is not configured."},
            )
        auth = request.headers.get("authorization")
        provided = None
        if auth and auth.lower().startswith("bearer "):
            provided = auth[7:].strip()
        elif request.headers.get("x-rsi-atlas-token"):
            provided = request.headers.get("x-rsi-atlas-token")
        if not tokens_match(provided=provided, expected=expected):
            return JSONResponse(status_code=401, content={"detail": "IPC authentication failed."})
        return await call_next(request)


__all__ = ["IpcAuthMiddleware"]
