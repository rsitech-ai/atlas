"""Strict release packaging honesty contracts for Phase 6 (sections 31-32)."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from json import dumps
from pathlib import PurePosixPath
from typing import Self

from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from rsi_atlas_contracts.document_parsing import DocumentContractModel

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_REPORT_ID_PATTERN = r"^releasecheck:[0-9a-f]{64}$"
_SBOM_ID_PATTERN = r"^sbom:[0-9a-f]{64}$"
_IDENTIFIER_PATTERN = r"^[a-zA-Z0-9][a-zA-Z0-9._+-]{0,127}$"


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


def _canonical_json(payload: object) -> str:
    return dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _require_bundle_relative_path(value: str, *, field_name: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or value != path.as_posix():
        raise ValueError(f"{field_name} must be a canonical bundle-relative path")
    return value


class SigningStatus(StrEnum):
    UNSIGNED_DEVELOPMENT = "unsigned_development"
    SIGNED_DEVELOPER_ID = "signed_developer_id"
    NOTARIZATION_BLOCKED = "notarization_blocked"
    NOTARIZED = "notarized"


class ReleaseClaim(StrEnum):
    DEVELOPMENT_ONLY = "development_only"
    RELEASE_CANDIDATE = "release_candidate"


class SbomComponent(DocumentContractModel):
    name: str = Field(pattern=_IDENTIFIER_PATTERN)
    version: str = Field(min_length=1, max_length=64)
    purl: str | None = Field(default=None, max_length=256)
    sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    license_expression: str | None = Field(default=None, min_length=1, max_length=256)
    license_files: tuple[str, ...] = ()

    @field_validator("license_files")
    @classmethod
    def _license_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for path in value:
            _require_bundle_relative_path(path, field_name="license_files")
        return value


class SbomFile(DocumentContractModel):
    path: str = Field(min_length=1, max_length=1024)
    sha256: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("path")
    @classmethod
    def _path(cls, value: str) -> str:
        return _require_bundle_relative_path(value, field_name="path")


class SbomDocument(DocumentContractModel):
    sbom_id: str = Field(pattern=_SBOM_ID_PATTERN)
    bom_format: str = Field(pattern=r"^CycloneDX$")
    spec_version: str = Field(pattern=r"^1\.5$")
    components: tuple[SbomComponent, ...] = Field(min_length=1)
    created_at: datetime
    source_lock_hash: str = Field(pattern=_SHA256_PATTERN)
    artifact_tree_sha256: str | None = Field(default=None, pattern=_SHA256_PATTERN)
    files: tuple[SbomFile, ...] = ()
    excluded_paths: tuple[str, ...] = ()

    @field_validator("excluded_paths")
    @classmethod
    def _excluded_paths(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for path in value:
            _require_bundle_relative_path(path, field_name="excluded_paths")
        return value

    @field_validator("created_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="created_at")


class PackageInventory(DocumentContractModel):
    bundle_path: str = Field(min_length=1, max_length=512)
    signing_status: SigningStatus
    python_embedded: StrictBool
    honesty_label: str = Field(min_length=1, max_length=128)
    component_count: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def _unsigned_honesty(self) -> Self:
        if (
            self.signing_status is SigningStatus.UNSIGNED_DEVELOPMENT
            and "unsigned" not in self.honesty_label.lower()
        ):
            raise ValueError("unsigned inventory must label honesty as unsigned")
        if (
            self.signing_status is SigningStatus.NOTARIZED
            and "unsigned" in self.honesty_label.lower()
        ):
            raise ValueError("notarized inventory cannot claim unsigned")
        return self


class ReleaseCheckReport(DocumentContractModel):
    report_id: str = Field(pattern=_REPORT_ID_PATTERN)
    claim: ReleaseClaim
    signing_status: SigningStatus
    notarization_status: SigningStatus
    sbom_present: StrictBool
    entitlement_matrix_present: StrictBool
    zero_egress_recorded: StrictBool
    blockers: tuple[str, ...] = ()
    release_ready: StrictBool
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="created_at")

    @model_validator(mode="after")
    def _fail_closed(self) -> Self:
        if self.claim is ReleaseClaim.RELEASE_CANDIDATE and self.release_ready:
            if self.signing_status is not SigningStatus.SIGNED_DEVELOPER_ID:
                raise ValueError("release candidate requires Developer ID signing")
            if self.notarization_status is not SigningStatus.NOTARIZED:
                raise ValueError("release candidate requires notarization")
            if not self.sbom_present:
                raise ValueError("release candidate requires SBOM")
        if self.release_ready and self.blockers:
            raise ValueError("release_ready cannot have blockers")
        if (
            not self.release_ready
            and self.claim is ReleaseClaim.RELEASE_CANDIDATE
            and not self.blockers
        ):
            raise ValueError("non-ready release claim requires blockers")
        if (
            self.notarization_status is SigningStatus.NOTARIZATION_BLOCKED
            and "notarization_blocked" not in self.blockers
            and self.release_ready
        ):
            raise ValueError("notarization blocked cannot be release ready")
        return self


def sbom_id(*, source_lock_hash: str, created_at: datetime) -> str:
    body = _canonical_json(
        {
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
            "source_lock_hash": source_lock_hash,
        }
    )
    return "sbom:" + sha256(body.encode("utf-8")).hexdigest()


def release_check_id(*, claim: ReleaseClaim, created_at: datetime) -> str:
    body = _canonical_json(
        {
            "claim": claim.value,
            "created_at": created_at.isoformat().replace("+00:00", "Z"),
        }
    )
    return "releasecheck:" + sha256(body.encode("utf-8")).hexdigest()
