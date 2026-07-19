"""Verify and restore development backups."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from rsi_atlas_contracts import BackupManifest, RestoreVerification


def load_manifest(backup_root: Path) -> BackupManifest:
    return BackupManifest.model_validate_json((backup_root / "manifest.json").read_bytes())


def verify_backup(backup_root: Path) -> RestoreVerification:
    manifest = load_manifest(backup_root)
    data_dir = backup_root / "data"
    missing: list[str] = []
    mismatched: list[str] = []
    for entry in manifest.entries:
        path = data_dir / entry.path
        if not path.is_file():
            missing.append(entry.path)
            continue
        digest = sha256(path.read_bytes()).hexdigest()
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


def restore_verified(backup_root: Path, destination: Path) -> RestoreVerification:
    """Copy backup data only after verification succeeds."""
    verification = verify_backup(backup_root)
    if not verification.verified:
        return verification
    destination.mkdir(parents=True, exist_ok=True)
    data_dir = backup_root / "data"
    for path in sorted(data_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(data_dir)
        target = destination / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    return verification
