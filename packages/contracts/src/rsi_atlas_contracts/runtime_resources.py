"""Explicit resource-root resolution for development and installed runtimes."""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

RESOURCE_ROOT_ENVIRONMENT_KEY = "RSI_ATLAS_RESOURCE_ROOT"


def resolve_resource_root(
    *,
    environ: Mapping[str, str] | None = None,
    development_fallback: Path | None = None,
) -> Path:
    """Resolve the repo-shaped read-only resource tree without installed-wheel inference."""
    values = os.environ if environ is None else environ
    raw = values.get(RESOURCE_ROOT_ENVIRONMENT_KEY)
    if raw is None:
        if development_fallback is None:
            raise ValueError("RSI Atlas resource root is not configured")
        candidate = development_fallback
    else:
        if not raw or raw != raw.strip():
            raise ValueError("runtime resource root is invalid")
        candidate = Path(raw)
    if not candidate.is_absolute():
        raise ValueError("runtime resource root must be absolute")
    if candidate != Path(os.path.normpath(candidate)):
        raise ValueError("runtime resource root must be canonical")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ValueError("runtime resource root is unavailable") from error
    if resolved != candidate:
        raise ValueError("runtime resource root must be canonical and must not be symlinked")
    metadata = resolved.stat()
    if stat.S_IMODE(metadata.st_mode) & 0o022:
        raise ValueError("runtime resource root must not be group or world writable")
    if not resolved.is_dir() or not (resolved / "migrations").is_dir():
        raise ValueError("runtime resource root must contain migrations")
    return resolved


@dataclass(frozen=True, slots=True)
class RuntimeResources:
    root: Path
    migration_root: Path
    document_worker_profile: Path

    @classmethod
    def resolve(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        development_fallback: Path | None = None,
    ) -> RuntimeResources:
        values = os.environ if environ is None else environ
        explicit = RESOURCE_ROOT_ENVIRONMENT_KEY in values
        root = resolve_resource_root(
            environ=values,
            development_fallback=development_fallback,
        )
        profile = (
            root / "security" / "document-worker.sb"
            if explicit
            else root / "infra" / "security" / "document-worker.sb"
        )
        if profile.is_symlink() or not profile.is_file() or profile.stat().st_size == 0:
            raise ValueError("runtime document-worker profile is missing or unsafe")
        return cls(
            root=root,
            migration_root=root / "migrations",
            document_worker_profile=profile,
        )


__all__ = [
    "RESOURCE_ROOT_ENVIRONMENT_KEY",
    "RuntimeResources",
    "resolve_resource_root",
]
