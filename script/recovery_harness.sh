#!/usr/bin/env bash
# Offline recovery helpers: backup → verify (Safe Mode/restore covered by package tests).
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export RSI_ATLAS_DATA_ROOT="${RSI_ATLAS_DATA_ROOT:-$ROOT_DIR/.local}"
export RSI_ATLAS_BACKUP_ROOT="${RSI_ATLAS_BACKUP_ROOT:-$ROOT_DIR/dist/backups}"
mkdir -p "$RSI_ATLAS_BACKUP_ROOT" "$RSI_ATLAS_DATA_ROOT"
cd "$ROOT_DIR"

uv run python - <<'PY'
from datetime import UTC, datetime
from pathlib import Path
import os
from rsi_atlas_contracts import BackupEncryptionStatus
from rsi_atlas_recovery import create_workspace_backup, verify_backup

root = Path(os.environ["RSI_ATLAS_DATA_ROOT"]).resolve()
backup_root = Path(os.environ["RSI_ATLAS_BACKUP_ROOT"]).resolve() / "harness"
backup_root.mkdir(parents=True, exist_ok=True)
if not any(root.rglob("*")):
    (root / ".keep").write_text("recovery-harness\n", encoding="utf-8")
manifest = create_workspace_backup(
    root,
    backup_root,
    created_at=datetime.now(tz=UTC),
    encryption_status=BackupEncryptionStatus.PLAINTEXT_DEV_ONLY,
)
verification = verify_backup(backup_root)
assert verification.verified is True
print(f"backup_id={manifest.backup_id}")
print("recovery harness ok")
PY
