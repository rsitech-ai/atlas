"""Shared parser candidate result schema (non-canonical)."""

from __future__ import annotations

from typing import Any, Protocol


class ParserCandidate(Protocol):
    name: str
    version: str
    tier: int

    def parse(self, *, artifact_fd: int, max_pages: int = 2000) -> dict[str, Any]: ...
