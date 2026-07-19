"""Strict backup, Safe Mode, and integrity contracts for Phase 6 (section 32)."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from json import dumps
from typing import Self

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from rsi_atlas_contracts.document_parsing import DocumentContractModel

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_BACKUP_ID_PATTERN = r"^backup:[0-9a-f]{64}$"
_SCRUB_ID_PATTERN = r"^scrub:[0-9a-f]{64}$"
_PATH_PATTERN = r"^[a-zA-Z0-9._/-]{1,512}$"
_IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


def _canonical_json(payload: object) -> str:
    return dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class BackupProductKind(StrEnum):
    RESEARCH_BUNDLE = "research_bundle"
    WORKSPACE = "workspace"
    DISASTER_RECOVERY = "disaster_recovery"


class BackupEncryptionStatus(StrEnum):
    DEVELOPMENT_PASSPHRASE = "development_passphrase"
    BLOCKED_KEYCHAIN_UNAVAILABLE = "blocked_keychain_unavailable"
    PLAINTEXT_DEV_ONLY = "plaintext_dev_only"
    FILE_KEY_AES_GCM = "file_key_aes_gcm"


class SafeModeCapability(StrEnum):
    COLLECTORS = "collectors"
    MODELS = "models"
    PARSER_WORKERS = "parser_workers"
    AUTOMATIC_MIGRATION = "automatic_migration"
    WORKFLOW_RESUMPTION = "workflow_resumption"


SAFE_MODE_DISABLED_CAPABILITIES = frozenset(SafeModeCapability)


class IntegrityFindingKind(StrEnum):
    MISSING = "missing"
    MODIFIED = "modified"
    ORPHAN = "orphan"
    OK = "ok"


class BackupEntry(DocumentContractModel):
    path: str = Field(pattern=_PATH_PATTERN)
    sha256: str = Field(pattern=_SHA256_PATTERN)
    size_bytes: StrictInt = Field(ge=0)


class BackupManifest(DocumentContractModel):
    backup_id: str = Field(pattern=_BACKUP_ID_PATTERN)
    kind: BackupProductKind
    created_at: datetime
    root_hash: str = Field(pattern=_SHA256_PATTERN)
    entries: tuple[BackupEntry, ...] = Field(min_length=1)
    encryption_status: BackupEncryptionStatus
    source_root: str = Field(pattern=_PATH_PATTERN)

    @field_validator("created_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="created_at")

    @model_validator(mode="after")
    def _unique_paths(self) -> Self:
        paths = [entry.path for entry in self.entries]
        if len(paths) != len(set(paths)):
            raise ValueError("backup entry paths must be unique")
        return self


class RestoreVerification(DocumentContractModel):
    backup_id: str = Field(pattern=_BACKUP_ID_PATTERN)
    verified: StrictBool
    mismatched_paths: tuple[str, ...] = ()
    missing_paths: tuple[str, ...] = ()
    detail: str = Field(default="", max_length=512)

    @model_validator(mode="after")
    def _verified_clean(self) -> Self:
        if self.verified and (self.mismatched_paths or self.missing_paths):
            raise ValueError("verified restore cannot report mismatches")
        if not self.verified and not (self.mismatched_paths or self.missing_paths or self.detail):
            raise ValueError("failed restore verification requires detail")
        return self


class SafeModeState(DocumentContractModel):
    active: StrictBool
    disabled_capabilities: frozenset[SafeModeCapability]
    entered_at: datetime | None = None
    reason: str = Field(default="", max_length=256)

    @field_validator("entered_at")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return _require_utc(value, field_name="entered_at")

    @model_validator(mode="after")
    def _active_disables_all(self) -> Self:
        if self.active:
            if self.disabled_capabilities != SAFE_MODE_DISABLED_CAPABILITIES:
                raise ValueError("active Safe Mode must disable the full capability set")
            if self.entered_at is None:
                raise ValueError("active Safe Mode requires entered_at")
        elif self.disabled_capabilities:
            raise ValueError("inactive Safe Mode must not list disabled capabilities")
        return self


class IntegrityScrubFinding(DocumentContractModel):
    path: str = Field(pattern=_PATH_PATTERN)
    kind: IntegrityFindingKind
    expected_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    actual_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)


class IntegrityScrubReport(DocumentContractModel):
    scrub_id: str = Field(pattern=_SCRUB_ID_PATTERN)
    findings: tuple[IntegrityScrubFinding, ...]
    healthy: StrictBool
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="created_at")

    @model_validator(mode="after")
    def _health(self) -> Self:
        bad = [f for f in self.findings if f.kind is not IntegrityFindingKind.OK]
        if self.healthy and bad:
            raise ValueError("healthy scrub cannot include non-ok findings")
        if not self.healthy and not bad:
            raise ValueError("unhealthy scrub requires findings")
        return self


def backup_id(*, root_hash: str, created_at: datetime, kind: BackupProductKind) -> str:
    body = _canonical_json(
        {
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "kind": kind.value,
            "root_hash": root_hash,
        }
    )
    return "backup:" + sha256(body.encode("utf-8")).hexdigest()


def scrub_id(*, root_hash: str, created_at: datetime) -> str:
    body = _canonical_json(
        {
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "root_hash": root_hash,
        }
    )
    return "scrub:" + sha256(body.encode("utf-8")).hexdigest()


def compute_root_hash(entries: tuple[BackupEntry, ...]) -> str:
    body = _canonical_json(
        [{"path": e.path, "sha256": e.sha256, "size_bytes": e.size_bytes} for e in entries]
    )
    return sha256(body.encode("utf-8")).hexdigest()
