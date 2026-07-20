from __future__ import annotations

from pathlib import Path

import pytest
from rsi_atlas_contracts.runtime_resources import RuntimeResources, resolve_resource_root


def _resource_root(path: Path) -> Path:
    path.mkdir()
    (path / "migrations").mkdir()
    security = path / "security"
    security.mkdir()
    (security / "document-worker.sb").write_text("(version 1)\n", encoding="utf-8")
    return path


def test_explicit_release_resource_root_wins_over_development_fallback(
    tmp_path: Path,
) -> None:
    release = _resource_root(tmp_path / "release")
    development = _resource_root(tmp_path / "development")

    resolved = resolve_resource_root(
        environ={"RSI_ATLAS_RESOURCE_ROOT": str(release)},
        development_fallback=development,
    )

    assert resolved == release


def test_resource_root_rejects_relative_symlinked_and_incomplete_paths(
    tmp_path: Path,
) -> None:
    real = _resource_root(tmp_path / "real")
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)

    with pytest.raises(ValueError, match="absolute"):
        resolve_resource_root(environ={"RSI_ATLAS_RESOURCE_ROOT": "relative"})
    with pytest.raises(ValueError, match="canonical"):
        resolve_resource_root(environ={"RSI_ATLAS_RESOURCE_ROOT": str(alias)})
    incomplete = tmp_path / "incomplete"
    incomplete.mkdir()
    with pytest.raises(ValueError, match="migrations"):
        resolve_resource_root(environ={"RSI_ATLAS_RESOURCE_ROOT": str(incomplete)})


def test_resource_root_fails_closed_without_explicit_or_development_root() -> None:
    with pytest.raises(ValueError, match="not configured"):
        resolve_resource_root(environ={})


def test_typed_release_resources_resolve_migrations_and_seatbelt_profile(
    tmp_path: Path,
) -> None:
    root = _resource_root(tmp_path / "release")

    resources = RuntimeResources.resolve(environ={"RSI_ATLAS_RESOURCE_ROOT": str(root)})

    assert resources.migration_root == root / "migrations"
    assert resources.document_worker_profile == root / "security" / "document-worker.sb"


def test_typed_resources_reject_missing_profile_and_writable_root(tmp_path: Path) -> None:
    root = _resource_root(tmp_path / "release")
    (root / "security" / "document-worker.sb").unlink()
    with pytest.raises(ValueError, match="profile"):
        RuntimeResources.resolve(environ={"RSI_ATLAS_RESOURCE_ROOT": str(root)})
    (root / "security" / "document-worker.sb").write_text("(version 1)\n")
    root.chmod(0o777)
    with pytest.raises(ValueError, match="writable"):
        RuntimeResources.resolve(environ={"RSI_ATLAS_RESOURCE_ROOT": str(root)})
