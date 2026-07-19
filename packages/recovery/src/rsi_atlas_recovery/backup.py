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

from rsi_atlas_recovery.file_key import encrypt_bytes, load_owner_key


def _iter_files(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file())


def create_workspace_backup(
    source_root: Path,
    destination_root: Path,
    *,
    created_at: datetime,
    encryption_status: BackupEncryptionStatus = BackupEncryptionStatus.PLAINTEXT_DEV_ONLY,
    owner_key_path: Path | None = None,
) -> BackupManifest:
    """Copy workspace files, write hashed manifest.

    Keychain wrap remains blocked. Optional FILE_KEY_AES_GCM uses an owner key file (0600).
    """
    if not source_root.is_dir():
        raise FileNotFoundError(f"source root missing: {source_root}")
    key: bytes | None = None
    if encryption_status is BackupEncryptionStatus.FILE_KEY_AES_GCM:
        if owner_key_path is None:
            raise ValueError("owner_key_path required for file_key_aes_gcm")
        key = load_owner_key(owner_key_path)
    elif encryption_status is BackupEncryptionStatus.BLOCKED_KEYCHAIN_UNAVAILABLE:
        raise ValueError(
            "keychain backup remains blocked; use plaintext_dev_only or file_key_aes_gcm"
        )
    destination_root.mkdir(parents=True, exist_ok=True)
    data_dir = destination_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    entries: list[BackupEntry] = []
    for path in _iter_files(source_root):
        rel = path.relative_to(source_root).as_posix()
        target = data_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = path.read_bytes()
        stored = encrypt_bytes(payload, key=key) if key is not None else payload
        target.write_bytes(stored)
        # Manifest hashes plaintext so restore can verify after decrypt.
        entries.append(
            BackupEntry(path=rel, sha256=sha256(payload).hexdigest(), size_bytes=len(payload))
        )
    if not entries:
        sentinel = data_dir / ".empty"
        empty = b""
        stored = encrypt_bytes(empty, key=key) if key is not None else empty
        sentinel.write_bytes(stored)
        entries.append(BackupEntry(path=".empty", sha256=sha256(empty).hexdigest(), size_bytes=0))
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
