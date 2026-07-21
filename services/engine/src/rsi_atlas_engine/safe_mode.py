"""Engine composition helpers for durable Safe Mode enforcement."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from psycopg import Connection
from rsi_atlas_contracts import SafeModeCapability
from rsi_atlas_recovery import SafeModeController, SafeModeStore
from rsi_atlas_storage import MigrationRunner
from rsi_atlas_storage.database import Row


def runtime_data_root(environ: Mapping[str, str] | None = None) -> Path:
    """Resolve the configured local runtime root without mutating the filesystem."""
    values = os.environ if environ is None else environ
    raw_data_root = values.get("RSI_ATLAS_DATA_ROOT")
    return (
        Path(raw_data_root)
        if raw_data_root is not None
        else Path.home() / "Library" / "Application Support" / "ai.rsitech.RSIAtlas"
    )


def runtime_safe_mode(environ: Mapping[str, str] | None = None) -> SafeModeController:
    """Resolve the file-backed controller for the configured local runtime root."""
    return SafeModeController(SafeModeStore(runtime_data_root(environ)))


def apply_or_verify_migrations(
    runner: MigrationRunner,
    controller: SafeModeController,
    *,
    connection: Connection[Row] | None = None,
) -> None:
    """Apply migrations normally, but perform a read-only verification in Safe Mode."""
    if controller.is_disabled(SafeModeCapability.AUTOMATIC_MIGRATION):
        runner.verify_all_applied(connection=connection)
        return
    runner.apply_all(connection=connection)


__all__ = ["apply_or_verify_migrations", "runtime_data_root", "runtime_safe_mode"]
