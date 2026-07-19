"""Recovery package tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from rsi_atlas_contracts import BackupEncryptionStatus, IntegrityFindingKind, SafeModeCapability
from rsi_atlas_recovery import (
    SafeModeController,
    create_workspace_backup,
    restore_verified,
    scrub_against_manifest,
    verify_backup,
)

NOW = datetime(2026, 7, 19, 16, 30, tzinfo=UTC)


def test_backup_restore_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "workspace"
    source.mkdir()
    (source / "note.txt").write_text("hello", encoding="utf-8")
    backup_root = tmp_path / "backup"
    manifest = create_workspace_backup(
        source,
        backup_root,
        created_at=NOW,
        encryption_status=BackupEncryptionStatus.PLAINTEXT_DEV_ONLY,
    )
    assert manifest.entries
    verification = verify_backup(backup_root)
    assert verification.verified is True
    dest = tmp_path / "restored"
    restored = restore_verified(backup_root, dest)
    assert restored.verified is True
    assert (dest / "note.txt").read_text(encoding="utf-8") == "hello"


def test_tamper_fails_verify(tmp_path: Path) -> None:
    source = tmp_path / "workspace"
    source.mkdir()
    (source / "note.txt").write_text("hello", encoding="utf-8")
    backup_root = tmp_path / "backup"
    create_workspace_backup(source, backup_root, created_at=NOW)
    (backup_root / "data" / "note.txt").write_text("tampered", encoding="utf-8")
    verification = verify_backup(backup_root)
    assert verification.verified is False
    assert "note.txt" in verification.mismatched_paths


def test_safe_mode_disables_capabilities() -> None:
    controller = SafeModeController()
    assert controller.is_disabled(SafeModeCapability.COLLECTORS) is False
    state = controller.enter(reason="scrub_failed", entered_at=NOW)
    assert state.active is True
    assert controller.is_disabled(SafeModeCapability.MODELS) is True
    assert controller.is_disabled(SafeModeCapability.AUTOMATIC_MIGRATION) is True
    controller.exit()
    assert controller.state.active is False


def test_scrub_detects_missing(tmp_path: Path) -> None:
    source = tmp_path / "workspace"
    source.mkdir()
    (source / "a.bin").write_bytes(b"abc")
    backup_root = tmp_path / "backup"
    manifest = create_workspace_backup(source, backup_root, created_at=NOW)
    scrub_root = tmp_path / "empty"
    scrub_root.mkdir()
    report = scrub_against_manifest(scrub_root, manifest, created_at=NOW)
    assert report.healthy is False
    assert any(f.kind is IntegrityFindingKind.MISSING for f in report.findings)
