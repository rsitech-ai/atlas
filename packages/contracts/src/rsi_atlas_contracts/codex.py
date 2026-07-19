"""Strict Codex engineering-plane contracts for Phase 6 (section 28 development slice)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from json import dumps
from typing import Self

from pydantic import Field, StrictBool, field_validator, model_validator

from rsi_atlas_contracts.document_parsing import DocumentContractModel

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_BUNDLE_ID_PATTERN = r"^codexbundle:[0-9a-f]{64}$"
_PATCH_ID_PATTERN = r"^candidatepatch:[0-9a-f]{64}$"
_GATE_ID_PATTERN = r"^patchgate:[0-9a-f]{64}$"
_IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_PATH_PATTERN = r"^[a-zA-Z0-9._/-]{1,512}$"


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


def _canonical_json(payload: object) -> str:
    return dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class CodexAuthorityAction(StrEnum):
    MERGE = "merge"
    PUSH = "push"
    DEPLOY = "deploy"
    PUBLISH_RESEARCH = "publish_research"
    PROMOTE_EVALUATION = "promote_evaluation"
    TRADE = "trade"
    SIGN = "sign"
    ACCESS_KEYCHAIN = "access_keychain"
    OPEN_NETWORK = "open_network"


BLOCKED_CODEX_AUTHORITY = frozenset(CodexAuthorityAction)


class CodexCommandClass(StrEnum):
    READ_SOURCE = "read_source"
    INSPECT = "inspect"
    FILE_CHANGE = "file_change"
    TEST = "test"
    DEPENDENCY_INSTALL = "dependency_install"
    NETWORK = "network"
    COMMIT = "commit"


class CodexApprovalStatus(StrEnum):
    ALLOWED = "allowed"
    REQUIRES_EXPLICIT_APPROVAL = "requires_explicit_approval"
    DENIED = "denied"


class CandidatePatchStatus(StrEnum):
    CANDIDATE = "candidate"
    GATE_FAILED = "gate_failed"
    GATE_PASSED = "gate_passed"
    REJECTED = "rejected"


class RedactionStatus(StrEnum):
    CLEAN = "clean"
    REDACTED = "redacted"
    BLOCKED = "blocked"


class SanitizedReproductionBundle(DocumentContractModel):
    bundle_id: str = Field(pattern=_BUNDLE_ID_PATTERN)
    failure_summary: str = Field(min_length=1, max_length=1024)
    source_versions: dict[str, str]
    sanitized_inputs: dict[str, object]
    expected_behavior: str = Field(min_length=1, max_length=1024)
    actual_behavior: str = Field(min_length=1, max_length=1024)
    deterministic_validator_results: tuple[str, ...] = ()
    permitted_commands: tuple[CodexCommandClass, ...]
    redaction_status: RedactionStatus
    redacted_paths: tuple[str, ...] = ()
    worktree_hint: str = Field(pattern=_PATH_PATTERN)
    network_denied: StrictBool = True
    credentials_denied: StrictBool = True
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="created_at")

    @model_validator(mode="after")
    def _strict_denials(self) -> Self:
        if not self.network_denied:
            raise ValueError("Codex bundles must deny network in strict mode")
        if not self.credentials_denied:
            raise ValueError("Codex bundles must deny production credentials")
        if CodexCommandClass.NETWORK in self.permitted_commands:
            raise ValueError("network command class cannot be permitted")
        if self.redaction_status is RedactionStatus.BLOCKED:
            raise ValueError("blocked redaction cannot form a bundle")
        for path in self.redacted_paths:
            if not path:
                raise ValueError("redacted path is invalid")
        for key, version in self.source_versions.items():
            if re.fullmatch(_IDENTIFIER_PATTERN, key) is None or not version:
                raise ValueError("source version entry is invalid")
        return self


class CodexApprovalDecision(DocumentContractModel):
    command_class: CodexCommandClass
    status: CodexApprovalStatus
    reason: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def _network_always_denied(self) -> Self:
        if (
            self.command_class is CodexCommandClass.NETWORK
            and self.status is not CodexApprovalStatus.DENIED
        ):
            raise ValueError("network commands are always denied")
        return self


class CandidatePatch(DocumentContractModel):
    patch_id: str = Field(pattern=_PATCH_ID_PATTERN)
    bundle_id: str = Field(pattern=_BUNDLE_ID_PATTERN)
    diff_hash: str = Field(pattern=_SHA256_PATTERN)
    status: CandidatePatchStatus = CandidatePatchStatus.CANDIDATE
    auto_applied: StrictBool = False
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="created_at")

    @model_validator(mode="after")
    def _no_auto_apply(self) -> Self:
        if self.auto_applied:
            raise ValueError("candidate patches cannot be auto-applied")
        return self


class PatchQualityCheck(DocumentContractModel):
    name: str = Field(pattern=_IDENTIFIER_PATTERN)
    passed: StrictBool
    detail: str = Field(default="", max_length=512)


class PatchQualityGateResult(DocumentContractModel):
    gate_id: str = Field(pattern=_GATE_ID_PATTERN)
    patch_id: str = Field(pattern=_PATCH_ID_PATTERN)
    checks: tuple[PatchQualityCheck, ...] = Field(min_length=1)
    passed: StrictBool
    blocking_failures: tuple[str, ...] = ()
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="created_at")

    @model_validator(mode="after")
    def _consistency(self) -> Self:
        failed = tuple(check.name for check in self.checks if not check.passed)
        if self.passed and failed:
            raise ValueError("gate cannot pass with failed checks")
        if not self.passed and not failed:
            raise ValueError("failed gate requires blocking failures")
        if tuple(self.blocking_failures) != failed:
            raise ValueError("blocking_failures must match failed check names")
        return self


class CodexAuthorityDenial(DocumentContractModel):
    action: CodexAuthorityAction
    denied: StrictBool = True
    reason: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def _always_denied(self) -> Self:
        if not self.denied:
            raise ValueError("Codex authority actions are always denied")
        if self.action not in BLOCKED_CODEX_AUTHORITY:
            raise ValueError("unknown Codex authority action")
        return self


def reproduction_bundle_id(*, failure_summary: str, diff_seed: str, created_at: datetime) -> str:
    body = _canonical_json(
        {
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "diff_seed": diff_seed,
            "failure_summary": failure_summary,
        }
    )
    return "codexbundle:" + sha256(body.encode("utf-8")).hexdigest()


def candidate_patch_id(*, bundle_id: str, diff_hash: str, created_at: datetime) -> str:
    body = _canonical_json(
        {
            "bundle_id": bundle_id,
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "diff_hash": diff_hash,
        }
    )
    return "candidatepatch:" + sha256(body.encode("utf-8")).hexdigest()


def patch_gate_id(*, patch_id: str, created_at: datetime) -> str:
    body = _canonical_json(
        {
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "patch_id": patch_id,
        }
    )
    return "patchgate:" + sha256(body.encode("utf-8")).hexdigest()
