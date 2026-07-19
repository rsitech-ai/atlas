"""Sanitize reproduction inputs for the Codex engineering plane."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from rsi_atlas_contracts import (
    CodexCommandClass,
    RedactionStatus,
    SanitizedReproductionBundle,
    reproduction_bundle_id,
)

from rsi_atlas_engineering.errors import RedactionBlocked

_SECRET_KEY_PATTERN = re.compile(
    r"(password|secret|token|api[_-]?key|authorization|private[_-]?key|keychain)",
    re.IGNORECASE,
)
_PROHIBITED_PATH_MARKERS = (
    "Keychain",
    "Library/Keychains",
    ".env",
    "credentials",
    "private_documents",
    "analyst_notes",
)


def _walk_redact(value: Any, *, path: str, redacted: list[str]) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if _SECRET_KEY_PATTERN.search(str(key)):
                redacted.append(child_path)
                out[key] = "[REDACTED]"
            else:
                out[key] = _walk_redact(child, path=child_path, redacted=redacted)
        return out
    if isinstance(value, list):
        return [
            _walk_redact(child, path=f"{path}[{index}]", redacted=redacted)
            for index, child in enumerate(value)
        ]
    if isinstance(value, str):
        for marker in _PROHIBITED_PATH_MARKERS:
            if marker in value:
                redacted.append(path or value)
                return "[REDACTED_PATH]"
    return value


def sanitize_reproduction_bundle(
    *,
    failure_summary: str,
    source_versions: dict[str, str],
    raw_inputs: dict[str, Any],
    expected_behavior: str,
    actual_behavior: str,
    deterministic_validator_results: tuple[str, ...],
    permitted_commands: tuple[CodexCommandClass, ...],
    worktree_hint: str,
    created_at: datetime,
    diff_seed: str = "dev",
) -> SanitizedReproductionBundle:
    """Build a sanitized bundle; fail closed if prohibited material remains unredactable."""
    for command in permitted_commands:
        if command is CodexCommandClass.NETWORK:
            raise RedactionBlocked("network_command_not_permitted")
    redacted_paths: list[str] = []
    sanitized = _walk_redact(raw_inputs, path="", redacted=redacted_paths)
    # Fail closed if any raw secret-looking string values remain under known keys.
    blob = str(sanitized)
    if any(marker in blob for marker in ("BEGIN PRIVATE KEY", "sk-live-", "AKIA")):
        raise RedactionBlocked("unredacted_secret_material")
    status = RedactionStatus.REDACTED if redacted_paths else RedactionStatus.CLEAN
    return SanitizedReproductionBundle(
        bundle_id=reproduction_bundle_id(
            failure_summary=failure_summary, diff_seed=diff_seed, created_at=created_at
        ),
        failure_summary=failure_summary,
        source_versions=source_versions,
        sanitized_inputs=sanitized,
        expected_behavior=expected_behavior,
        actual_behavior=actual_behavior,
        deterministic_validator_results=deterministic_validator_results,
        permitted_commands=permitted_commands,
        redaction_status=status,
        redacted_paths=tuple(redacted_paths),
        worktree_hint=worktree_hint,
        created_at=created_at,
    )
