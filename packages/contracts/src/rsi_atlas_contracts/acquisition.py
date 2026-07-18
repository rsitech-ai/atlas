from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import PurePath
from typing import Literal
from unicodedata import category, normalize
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from rsi_atlas_contracts.artifact import (
    ArtifactCommandContext,
    ArtifactDescriptor,
    ArtifactID,
)
from rsi_atlas_contracts.system_status import StrictModel


class AcquisitionMethod(StrEnum):
    MANUAL_NATIVE = "manual_native"
    MANUAL_CLI = "manual_cli"
    LOCAL_API = "local_api"


class NetworkProfile(StrEnum):
    OFFLINE = "offline"


class DocumentLifecycle(StrEnum):
    QUARANTINED = "quarantined"
    AWAITING_REVIEW = "awaiting_review"
    AWAITING_PASSWORD = "awaiting_password"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class AdmissionOutcome(StrEnum):
    ACCEPT = "accept"
    ACCEPT_WITH_RESTRICTIONS = "accept_with_restrictions"
    REQUEST_PASSWORD = "request_password"
    QUARANTINE_FOR_REVIEW = "quarantine_for_review"
    REJECT_POLICY_VIOLATION = "reject_policy_violation"
    REJECT_UNSAFE = "reject_unsafe"
    MARK_EXACT_DUPLICATE = "mark_exact_duplicate"
    REGISTER_NEW_VERSION = "register_new_version"


class SafetyCheckState(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class AcquisitionRequest(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    acquisition_id: UUID
    method: AcquisitionMethod
    original_filename: str = Field(min_length=1, max_length=255)
    source_locator: str = Field(min_length=1, max_length=64)
    declared_media_type: Literal["application/pdf"]
    collector_version: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    network_profile: Literal[NetworkProfile.OFFLINE] = NetworkProfile.OFFLINE

    @field_validator("original_filename")
    @classmethod
    def validate_original_filename(cls, value: str) -> str:
        if normalize("NFC", value) != value:
            raise ValueError("original filename must use Unicode NFC")
        if value in {".", ".."} or PurePath(value).name != value:
            raise ValueError("original filename must be a leaf name")
        if "/" in value or "\\" in value or any(category(character) == "Cc" for character in value):
            raise ValueError("original filename contains forbidden characters")
        if not value.casefold().endswith(".pdf"):
            raise ValueError("original filename must have a PDF extension")
        return value

    @model_validator(mode="after")
    def locator_matches_acquisition(self) -> "AcquisitionRequest":
        expected = f"manual-import:{self.acquisition_id}"
        if self.source_locator != expected:
            raise ValueError("source locator must match the acquisition identity")
        return self


class PDFSafetyProfile(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    policy_version: Literal["phase-2a-1"] = "phase-2a-1"
    artifact_id: ArtifactID = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=1, le=33_554_432)
    header_version: str | None = Field(default=None, pattern=r"^1\.[0-7]$")
    eof_marker_present: bool
    page_marker_count: int | None = Field(default=None, ge=0, le=2_001)
    mime_signature_consistency: SafetyCheckState
    size_limit: SafetyCheckState
    page_count_limit: SafetyCheckState
    encryption_password_state: SafetyCheckState
    malformed_structure: SafetyCheckState
    embedded_files: SafetyCheckState
    active_actions: SafetyCheckState
    suspicious_references: SafetyCheckState
    decompression_ratio: SafetyCheckState
    source_policy: SafetyCheckState
    available_disk: SafetyCheckState
    inspected_at: datetime

    @field_validator("inspected_at")
    @classmethod
    def inspected_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="inspected_at")

    @model_validator(mode="after")
    def identifier_matches_digest(self) -> "PDFSafetyProfile":
        if self.artifact_id != f"sha256:{self.digest}":
            raise ValueError("safety profile artifact identifier must match its digest")
        return self


_PHASE_TWO_A_LIFECYCLE = {
    AdmissionOutcome.QUARANTINE_FOR_REVIEW: DocumentLifecycle.AWAITING_REVIEW,
    AdmissionOutcome.REQUEST_PASSWORD: DocumentLifecycle.AWAITING_PASSWORD,
    AdmissionOutcome.REJECT_POLICY_VIOLATION: DocumentLifecycle.REJECTED,
    AdmissionOutcome.REJECT_UNSAFE: DocumentLifecycle.REJECTED,
    AdmissionOutcome.MARK_EXACT_DUPLICATE: DocumentLifecycle.DUPLICATE,
}


class DocumentAdmissionRecord(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    context: ArtifactCommandContext
    request: AcquisitionRequest
    artifact: ArtifactDescriptor
    profile: PDFSafetyProfile
    lifecycle: DocumentLifecycle
    outcome: AdmissionOutcome
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=32)
    duplicate_of_acquisition_id: UUID | None = None
    recorded_at: datetime

    @field_validator("reason_codes")
    @classmethod
    def reasons_are_canonical(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(
            not reason
            or len(reason) > 64
            or not reason[0].isalpha()
            or reason != reason.casefold()
            or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_" for character in reason)
            for reason in value
        ):
            raise ValueError("reason codes must be lowercase identifiers")
        if tuple(sorted(set(value))) != value:
            raise ValueError("reason codes must be unique and sorted")
        return value

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="recorded_at")

    @model_validator(mode="after")
    def record_is_consistent(self) -> "DocumentAdmissionRecord":
        expected_lifecycle = _PHASE_TWO_A_LIFECYCLE.get(self.outcome)
        if expected_lifecycle is None:
            raise ValueError("Phase 2A cannot record an accepted or new-version outcome")
        if self.lifecycle is not expected_lifecycle:
            raise ValueError("admission lifecycle is inconsistent with the outcome")

        is_duplicate = self.outcome is AdmissionOutcome.MARK_EXACT_DUPLICATE
        if is_duplicate != (self.duplicate_of_acquisition_id is not None):
            raise ValueError("exact duplicate outcome and duplicate target must appear together")
        if self.duplicate_of_acquisition_id == self.request.acquisition_id:
            raise ValueError("an acquisition cannot duplicate itself")

        expected_profile = (
            str(self.artifact.artifact_id),
            self.artifact.digest,
            self.artifact.size_bytes,
        )
        actual_profile = (
            str(self.profile.artifact_id),
            self.profile.digest,
            self.profile.size_bytes,
        )
        if actual_profile != expected_profile:
            raise ValueError("safety profile does not match the immutable artifact")
        if self.artifact.media_type != "application/pdf":
            raise ValueError("document admission requires an application/pdf artifact")
        return self


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value
