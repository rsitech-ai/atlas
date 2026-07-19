"""Engineering-plane errors."""

from __future__ import annotations


class EngineeringError(RuntimeError):
    """Base Codex product-plane error."""


class RedactionBlocked(EngineeringError):
    def __init__(self, reason: str = "redaction_blocked") -> None:
        self.code = reason
        super().__init__(reason)


class AuthorityDenied(EngineeringError):
    def __init__(self, action: str) -> None:
        self.code = "authority_denied"
        self.action = action
        super().__init__(f"Codex authority denied: {action}")
