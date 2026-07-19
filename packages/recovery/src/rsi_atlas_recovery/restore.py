"""Verify and restore development backups."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from rsi_atlas_contracts import BackupEncryptionStatus, BackupManifest, RestoreVerification

from rsi_atlas_recovery.file_key import decrypt_bytes, load_owner_key


def load_manifest(backup_root: Path) -> BackupManifest:
    return BackupManifest.model_validate_json((backup_root / "manifest.json").read_bytes())


def verify_backup(
    backup_root: Path,
    *,
    owner_key_path: Path | None = None,
) -> RestoreVerification:
    manifest = load_manifest(backup_root)
    data_dir = backup_root / "data"
    key: bytes | None = None
    if manifest.encryption_status is BackupEncryptionStatus.FILE_KEY_AES_GCM:
        if owner_key_path is None:
            return RestoreVerification(
                backup_id=manifest.backup_id,
                verified=False,
                detail="owner_key_path required to verify file_key_aes_gcm backup",
            )
        key = load_owner_key(owner_key_path)
    missing: list[str] = []
    mismatched: list[str] = []
    for entry in manifest.entries:
        path = data_dir / entry.path
        if not path.is_file():
            missing.append(entry.path)
            continue
        blob = path.read_bytes()
        payload = decrypt_bytes(blob, key=key) if key is not None else blob
        digest = sha256(payload).hexdigest()
        if digest != entry.sha256:
            mismatched.append(entry.path)
    verified = not missing and not mismatched
    return RestoreVerification(
        backup_id=manifest.backup_id,
        verified=verified,
        mismatched_paths=tuple(mismatched),
        missing_paths=tuple(missing),
        detail="" if verified else "hash or presence failure",
    )


def restore_verified(
    backup_root: Path,
    destination: Path,
    *,
    owner_key_path: Path | None = None,
) -> RestoreVerification:
    """Copy backup data only after verification succeeds."""
    verification = verify_backup(backup_root, owner_key_path=owner_key_path)
    if not verification.verified:
        return verification
    manifest = load_manifest(backup_root)
    key: bytes | None = None
    if manifest.encryption_status is BackupEncryptionStatus.FILE_KEY_AES_GCM:
        if owner_key_path is None:
            return RestoreVerification(
                backup_id=manifest.backup_id,
                verified=False,
                detail="owner_key_path required to restore file_key_aes_gcm backup",
            )
        key = load_owner_key(owner_key_path)
    destination.mkdir(parents=True, exist_ok=True)
    data_dir = backup_root / "data"
    for path in sorted(data_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(data_dir)
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        blob = path.read_bytes()
        payload = decrypt_bytes(blob, key=key) if key is not None else blob
        target.write_bytes(payload)
    return verification
