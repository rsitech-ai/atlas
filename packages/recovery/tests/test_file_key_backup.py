"""File-key backup and OCR fail-closed tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from rsi_atlas_contracts import BackupEncryptionStatus
from rsi_atlas_document_worker.ocr import OcrUnavailable, require_tesseract
from rsi_atlas_recovery import (
    create_workspace_backup,
    generate_owner_key_file,
    restore_verified,
    verify_backup,
)


def test_file_key_backup_roundtrip(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (source / "note.txt").write_text("secret research note", encoding="utf-8")
    key = generate_owner_key_file(tmp_path / "owner.key")
    backup = tmp_path / "backup"
    create_workspace_backup(
        source,
        backup,
        created_at=datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        encryption_status=BackupEncryptionStatus.FILE_KEY_AES_GCM,
        owner_key_path=key,
    )
    verified = verify_backup(backup, owner_key_path=key)
    assert verified.verified is True
    dest = tmp_path / "restored"
    restore_verified(backup, dest, owner_key_path=key)
    assert (dest / "note.txt").read_text(encoding="utf-8") == "secret research note"


def test_ocr_fail_closed_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "rsi_atlas_document_worker.ocr.shutil.which",
        lambda _name: None,
    )
    with pytest.raises(OcrUnavailable, match="blocked_ocr_unavailable"):
        require_tesseract()
