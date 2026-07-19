"""Codex App Server live qualification gate (fail-closed without binary)."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CodexQualification:
    available: bool
    binary_path: str | None
    blockers: tuple[str, ...]
    deny_network_required: bool = True
    isolated_worktree_required: bool = True


def qualify_codex_app_server(*, worktree_hint: Path | None = None) -> CodexQualification:
    """Probe for a local Codex binary; never claim live qualification without it."""
    blockers: list[str] = []
    binary = shutil.which("codex") or os.environ.get("RSI_ATLAS_CODEX_BIN", "").strip() or None
    if binary is None or (not Path(binary).is_file() and shutil.which(binary or "") is None):
        # which returns path; env may be absolute
        if binary and Path(binary).is_file():
            pass
        else:
            blockers.append("codex_binary_missing")
            binary = None
    if worktree_hint is not None and not worktree_hint.exists():
        blockers.append("isolated_worktree_missing")
    if os.environ.get("RSI_ATLAS_CODEX_ALLOW_NETWORK", "").strip() in {"1", "true", "yes"}:
        blockers.append("deny_network_violated")
    available = not blockers and binary is not None
    if available:
        # Live App Server suite still requires manual/owner evidence; machinery only.
        blockers.append("live_app_server_suite_not_executed")
        available = False
    return CodexQualification(
        available=available,
        binary_path=binary,
        blockers=tuple(blockers),
    )


__all__ = ["CodexQualification", "qualify_codex_app_server"]
