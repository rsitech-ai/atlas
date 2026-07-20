"""Strict Codex engineering-plane contracts for Phase 6 (section 28 development slice)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from json import dumps
from types import MappingProxyType
from typing import Self

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from rsi_atlas_contracts.document_parsing import DocumentContractModel

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_BUNDLE_ID_PATTERN = r"^codexbundle:[0-9a-f]{64}$"
_PATCH_ID_PATTERN = r"^candidatepatch:[0-9a-f]{64}$"
_GATE_ID_PATTERN = r"^patchgate:[0-9a-f]{64}$"
_EVIDENCE_ID_PATTERN = r"^patchtestevidence:[0-9a-f]{64}$"
_BASE_COMMIT_PATTERN = r"^[0-9a-f]{40}$"
_RUNNER_VERSION_PATTERN = r"^rsi-atlas-trusted-runner/[0-9]+\.[0-9]+\.[0-9]+$"
_IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_PATH_PATTERN = r"^[a-zA-Z0-9._/-]{1,512}$"
MAX_PATCH_TEST_OUTPUT_BYTES = 1_048_576
MAX_PATCH_TEST_DURATION = timedelta(minutes=30)


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


class PatchTestSuite(StrEnum):
    REPOSITORY_FULL_REGRESSION = "repository_full_regression"


PATCH_TEST_SUITE_ARGV: Mapping[PatchTestSuite, tuple[str, ...]] = MappingProxyType(
    {PatchTestSuite.REPOSITORY_FULL_REGRESSION: ("./script/codex_full_regression.sh",)}
)


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
    base_commit: str | None = Field(default=None, pattern=_BASE_COMMIT_PATTERN)
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
        expected_id = candidate_patch_id(
            bundle_id=self.bundle_id,
            diff_hash=self.diff_hash,
            base_commit=self.base_commit,
            created_at=self.created_at,
        )
        if self.patch_id != expected_id:
            raise ValueError("patch_id must match the canonical candidate patch payload")
        return self


class PatchTestEvidence(DocumentContractModel):
    evidence_id: str = Field(pattern=_EVIDENCE_ID_PATTERN)
    patch_id: str = Field(pattern=_PATCH_ID_PATTERN)
    diff_hash: str = Field(pattern=_SHA256_PATTERN)
    base_commit: str = Field(pattern=_BASE_COMMIT_PATTERN)
    suite_id: PatchTestSuite
    argv: tuple[str, ...] = Field(min_length=1)
    passed: StrictBool
    exit_code: StrictInt = Field(ge=0, le=255)
    started_at: datetime
    completed_at: datetime
    stdout_sha256: str = Field(pattern=_SHA256_PATTERN)
    stdout_bytes: StrictInt = Field(ge=0, le=MAX_PATCH_TEST_OUTPUT_BYTES)
    stderr_sha256: str = Field(pattern=_SHA256_PATTERN)
    stderr_bytes: StrictInt = Field(ge=0, le=MAX_PATCH_TEST_OUTPUT_BYTES)
    runner_version: str = Field(pattern=_RUNNER_VERSION_PATTERN)

    @field_validator("started_at", "completed_at")
    @classmethod
    def _utc(cls, value: datetime, info: object) -> datetime:
        field_name = getattr(info, "field_name", "test timestamp")
        return _require_utc(value, field_name=field_name)

    @model_validator(mode="after")
    def _strict_execution_evidence(self) -> Self:
        if self.argv != PATCH_TEST_SUITE_ARGV[self.suite_id]:
            raise ValueError("argv must exactly match the allowlisted test suite command")
        if self.passed is not (self.exit_code == 0):
            raise ValueError("passed must agree with the process exit code")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        if self.completed_at - self.started_at > MAX_PATCH_TEST_DURATION:
            raise ValueError("test evidence duration exceeds the bounded runtime")
        expected_id = patch_test_evidence_id(
            patch_id=self.patch_id,
            diff_hash=self.diff_hash,
            base_commit=self.base_commit,
            suite_id=self.suite_id,
            argv=self.argv,
            passed=self.passed,
            exit_code=self.exit_code,
            started_at=self.started_at,
            completed_at=self.completed_at,
            stdout_sha256=self.stdout_sha256,
            stdout_bytes=self.stdout_bytes,
            stderr_sha256=self.stderr_sha256,
            stderr_bytes=self.stderr_bytes,
            runner_version=self.runner_version,
        )
        if self.evidence_id != expected_id:
            raise ValueError("evidence_id must match the canonical test evidence payload")
        return self


class PatchQualityCheck(DocumentContractModel):
    name: str = Field(pattern=_IDENTIFIER_PATTERN)
    passed: StrictBool
    detail: str = Field(default="", max_length=512)


class PatchQualityGateResult(DocumentContractModel):
    gate_id: str = Field(pattern=_GATE_ID_PATTERN)
    patch_id: str = Field(pattern=_PATCH_ID_PATTERN)
    diff_hash: str = Field(pattern=_SHA256_PATTERN)
    base_commit: str | None = Field(pattern=_BASE_COMMIT_PATTERN)
    checks: tuple[PatchQualityCheck, ...] = Field(min_length=1)
    passed: StrictBool
    blocking_failures: tuple[str, ...] = ()
    test_evidence: tuple[PatchTestEvidence, ...] = ()
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
        evidence_matches = bool(self.test_evidence) and all(
            evidence.patch_id == self.patch_id
            and evidence.diff_hash == self.diff_hash
            and evidence.base_commit == self.base_commit
            and evidence.passed
            and evidence.exit_code == 0
            for evidence in self.test_evidence
        )
        if self.passed and (self.base_commit is None or not evidence_matches):
            raise ValueError("passed gate requires matching successful test evidence")
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


def candidate_patch_id(
    *,
    bundle_id: str,
    diff_hash: str,
    created_at: datetime,
    base_commit: str | None = None,
) -> str:
    body = _canonical_json(
        {
            "bundle_id": bundle_id,
            "base_commit": base_commit,
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "diff_hash": diff_hash,
        }
    )
    return "candidatepatch:" + sha256(body.encode("utf-8")).hexdigest()


def patch_test_evidence_id(
    *,
    patch_id: str,
    diff_hash: str,
    base_commit: str,
    suite_id: PatchTestSuite,
    argv: tuple[str, ...],
    passed: bool,
    exit_code: int,
    started_at: datetime,
    completed_at: datetime,
    stdout_sha256: str,
    stdout_bytes: int,
    stderr_sha256: str,
    stderr_bytes: int,
    runner_version: str,
) -> str:
    body = _canonical_json(
        {
            "argv": argv,
            "base_commit": base_commit,
            "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
            "diff_hash": diff_hash,
            "exit_code": exit_code,
            "passed": passed,
            "patch_id": patch_id,
            "runner_version": runner_version,
            "started_at": started_at.isoformat().replace("+00:00", "Z"),
            "stderr_bytes": stderr_bytes,
            "stderr_sha256": stderr_sha256,
            "stdout_bytes": stdout_bytes,
            "stdout_sha256": stdout_sha256,
            "suite_id": suite_id,
        }
    )
    return "patchtestevidence:" + sha256(body.encode("utf-8")).hexdigest()


def patch_gate_id(*, patch_id: str, created_at: datetime) -> str:
    body = _canonical_json(
        {
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "patch_id": patch_id,
        }
    )
    return "patchgate:" + sha256(body.encode("utf-8")).hexdigest()
