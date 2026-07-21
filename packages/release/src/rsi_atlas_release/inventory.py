"""Unsigned package inventory honesty."""

from __future__ import annotations

from pathlib import Path

from rsi_atlas_contracts import PackageInventory, SigningStatus


def inventory_staged_bundle(bundle_path: Path) -> PackageInventory:
    """Describe staged contents without upgrading unsigned code to release evidence."""
    exists = bundle_path.exists()
    count = 0
    if exists and bundle_path.is_dir():
        count = sum(1 for path in bundle_path.rglob("*") if path.is_file())
    python = bundle_path / "Contents" / "Resources" / "runtime" / "python" / "bin" / "python3"
    python_embedded = python.is_file() and not python.is_symlink()
    return PackageInventory(
        bundle_path=bundle_path.as_posix(),
        signing_status=SigningStatus.UNSIGNED_DEVELOPMENT,
        python_embedded=python_embedded,
        honesty_label="unsigned_development",
        component_count=count,
    )
