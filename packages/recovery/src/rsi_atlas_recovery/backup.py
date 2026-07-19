"""Development filesystem backup barrier."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path

from rsi_atlas_contracts import (
    BackupEncryptionStatus,
    BackupEntry,
    BackupManifest,
    BackupProductKind,
    backup_id,
    compute_root_hash,
)


def _iter_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def create_workspace_backup(
    source_root: Path,
    destination_root: Path,
    *,
    created_at: datetime,
    encryption_status: BackupEncryptionStatus = BackupEncryptionStatus.PLAINTEXT_DEV_ONLY,
) -> BackupManifest:
    """Copy workspace files, write hashed manifest. Keychain wrap remains blocked."""
    if not source_root.is_dir():
        raise FileNotFoundError(f"source root missing: {source_root}")
    destination_root.mkdir(parents=True, exist_ok=True)
    data_dir = destination_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    entries: list[BackupEntry] = []
    for path in _iter_files(source_root):
        rel = path.relative_to(source_root).as_posix()
        target = data_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = path.read_bytes()
        target.write_bytes(payload)
        entries.append(
            BackupEntry(path=rel, sha256=sha256(payload).hexdigest(), size_bytes=len(payload))
        )
    if not entries:
        # empty workspace still needs a sentinel for contract min_length
        sentinel = data_dir / ".empty"
        sentinel.write_bytes(b"")
        entries.append(BackupEntry(path=".empty", sha256=sha256(b"").hexdigest(), size_bytes=0))
    entry_tuple = tuple(entries)
    root_hash = compute_root_hash(entry_tuple)
    manifest = BackupManifest(
        backup_id=backup_id(
            root_hash=root_hash, created_at=created_at, kind=BackupProductKind.WORKSPACE
        ),
        kind=BackupProductKind.WORKSPACE,
        created_at=created_at,
        root_hash=root_hash,
        entries=entry_tuple,
        encryption_status=encryption_status,
        source_root=source_root.as_posix(),
    )
    (destination_root / "manifest.json").write_bytes(manifest.model_dump_json(indent=2).encode())
    return manifest
