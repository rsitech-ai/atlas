"""Strict Phase 6 recovery contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from rsi_atlas_contracts.recovery import (
    SAFE_MODE_DISABLED_CAPABILITIES,
    BackupEncryptionStatus,
    BackupEntry,
    BackupManifest,
    BackupProductKind,
    IntegrityFindingKind,
    IntegrityScrubFinding,
    IntegrityScrubReport,
    RestoreVerification,
    SafeModeCapability,
    SafeModeState,
    backup_id,
    compute_root_hash,
    scrub_id,
)

NOW = datetime(2026, 7, 19, 16, 0, tzinfo=UTC)


def _entry(path: str = "artifacts/a.bin", digest: str | None = None) -> BackupEntry:
    return BackupEntry(path=path, sha256=digest or ("a" * 64), size_bytes=3)


def test_backup_manifest_unique_paths() -> None:
    entries = (_entry(), _entry())
    root = compute_root_hash(entries)
    with pytest.raises(ValidationError, match="unique"):
        BackupManifest(
            backup_id=backup_id(root_hash=root, created_at=NOW, kind=BackupProductKind.WORKSPACE),
            kind=BackupProductKind.WORKSPACE,
            created_at=NOW,
            root_hash=root,
            entries=entries,
            encryption_status=BackupEncryptionStatus.PLAINTEXT_DEV_ONLY,
            source_root="tmp/workspace",
        )


def test_safe_mode_requires_full_disable_set() -> None:
    state = SafeModeState(
        active=True,
        disabled_capabilities=SAFE_MODE_DISABLED_CAPABILITIES,
        entered_at=NOW,
        reason="integrity",
    )
    assert SafeModeCapability.COLLECTORS in state.disabled_capabilities
    with pytest.raises(ValidationError, match="full capability"):
        SafeModeState(
            active=True,
            disabled_capabilities=frozenset({SafeModeCapability.COLLECTORS}),
            entered_at=NOW,
            reason="partial",
        )


def test_restore_verification_consistency() -> None:
    bid = backup_id(root_hash="b" * 64, created_at=NOW, kind=BackupProductKind.WORKSPACE)
    ok = RestoreVerification(backup_id=bid, verified=True)
    assert ok.verified is True
    with pytest.raises(ValidationError, match="mismatches"):
        RestoreVerification(
            backup_id=bid,
            verified=True,
            mismatched_paths=("artifacts/a.bin",),
        )


def test_scrub_report_health() -> None:
    sid = scrub_id(root_hash="c" * 64, created_at=NOW)
    report = IntegrityScrubReport(
        scrub_id=sid,
        findings=(
            IntegrityScrubFinding(path="artifacts/a.bin", kind=IntegrityFindingKind.MISSING),
        ),
        healthy=False,
        created_at=NOW,
    )
    assert report.healthy is False
    with pytest.raises(ValidationError, match="healthy"):
        IntegrityScrubReport(
            scrub_id=sid,
            findings=(
                IntegrityScrubFinding(path="artifacts/a.bin", kind=IntegrityFindingKind.MISSING),
            ),
            healthy=True,
            created_at=NOW,
        )


def test_keychain_encryption_status_allowed_as_blocked_marker() -> None:
    entry = _entry()
    entries = (entry,)
    root = compute_root_hash(entries)
    manifest = BackupManifest(
        backup_id=backup_id(root_hash=root, created_at=NOW, kind=BackupProductKind.WORKSPACE),
        kind=BackupProductKind.WORKSPACE,
        created_at=NOW,
        root_hash=root,
        entries=entries,
        encryption_status=BackupEncryptionStatus.BLOCKED_KEYCHAIN_UNAVAILABLE,
        source_root="tmp/workspace",
    )
    assert manifest.encryption_status is BackupEncryptionStatus.BLOCKED_KEYCHAIN_UNAVAILABLE
