"""Always-deny Codex automatic authority."""

from __future__ import annotations

from rsi_atlas_contracts import BLOCKED_CODEX_AUTHORITY, CodexAuthorityAction, CodexAuthorityDenial

from rsi_atlas_engineering.errors import AuthorityDenied


def deny_authority(action: CodexAuthorityAction) -> CodexAuthorityDenial:
    """Record and raise denial for any automatic authority action."""
    if action not in BLOCKED_CODEX_AUTHORITY:
        raise AuthorityDenied(action.value)
    raise AuthorityDenied(action.value)


def authority_denial(action: CodexAuthorityAction) -> CodexAuthorityDenial:
    """Return a typed denial record without raising (for API responses)."""
    return CodexAuthorityDenial(
        action=action,
        denied=True,
        reason=f"Codex cannot {action.value} automatically",
    )
