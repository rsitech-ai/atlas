from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol, Self
from uuid import UUID

from pydantic import Field, StrictBytes, StrictInt, model_validator
from rsi_atlas_contracts import (
    AcquisitionRequest,
    ArtifactCommandContext,
    ArtifactDescriptor,
    ArtifactID,
    DocumentAdmissionRecord,
    PDFSafetyProfile,
    SafetyCheckState,
)
from rsi_atlas_contracts.system_status import StrictModel

from rsi_atlas_ingestion.admission import PDFAdmissionDecision, PDFAdmissionPolicy

MAX_PDF_BYTES = 33_554_432
_LEADING_EVIDENCE_BYTES = 8
_TRAILING_EVIDENCE_BYTES = 1_024
_PDF_TRAILING_WHITESPACE = b" \t\r\n\f"


class StagedPDFEvidenceMismatchError(RuntimeError):
    """Raised when independently staged evidence differs from immutable CAS evidence."""


class StagedPDFEvidence(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: StrictInt = Field(ge=1, le=MAX_PDF_BYTES)
    leading_bytes: StrictBytes = Field(min_length=1, max_length=_LEADING_EVIDENCE_BYTES)
    trailing_bytes: StrictBytes = Field(min_length=1, max_length=_TRAILING_EVIDENCE_BYTES)
    source_policy: SafetyCheckState
    available_disk: SafetyCheckState

    @model_validator(mode="after")
    def evidence_windows_are_exact(self) -> Self:
        expected_leading = min(self.size_bytes, _LEADING_EVIDENCE_BYTES)
        if len(self.leading_bytes) != expected_leading:
            raise ValueError("leading bytes must cover the exact bounded prefix")
        expected_trailing = min(self.size_bytes, _TRAILING_EVIDENCE_BYTES)
        if len(self.trailing_bytes) != expected_trailing:
            raise ValueError("trailing bytes must cover the exact bounded suffix")
        return self

    def require_matches(self, descriptor: ArtifactDescriptor) -> None:
        checked_descriptor = ArtifactDescriptor.model_validate(descriptor)
        if (
            self.digest,
            self.size_bytes,
        ) != (
            checked_descriptor.digest,
            checked_descriptor.size_bytes,
        ):
            raise StagedPDFEvidenceMismatchError(
                "staged PDF evidence does not match the immutable artifact"
            )


class ArtifactStorePort(Protocol):
    def put_file(
        self,
        source: Path,
        *,
        media_type: str,
        max_bytes: int,
        context: ArtifactCommandContext,
    ) -> ArtifactDescriptor: ...


class ArtifactRepositoryPort(Protocol):
    def register(
        self, *, context: ArtifactCommandContext, descriptor: ArtifactDescriptor
    ) -> ArtifactDescriptor: ...


class AcquisitionRepositoryPort(Protocol):
    def find_duplicate(
        self, *, context: ArtifactCommandContext, artifact_id: ArtifactID
    ) -> UUID | None: ...

    def record(self, record: DocumentAdmissionRecord) -> DocumentAdmissionRecord: ...


class AdmissionPolicyPort(Protocol):
    def evaluate(
        self,
        *,
        profile: PDFSafetyProfile,
        request: AcquisitionRequest,
        duplicate_of_acquisition_id: UUID | None,
    ) -> PDFAdmissionDecision: ...


class DocumentAdmissionService:
    def __init__(
        self,
        *,
        artifact_store: ArtifactStorePort,
        artifact_repository: ArtifactRepositoryPort,
        acquisition_repository: AcquisitionRepositoryPort,
        policy: AdmissionPolicyPort | None = None,
        clock: Callable[[], datetime],
    ) -> None:
        self._artifact_store = artifact_store
        self._artifact_repository = artifact_repository
        self._acquisition_repository = acquisition_repository
        self._policy = policy or PDFAdmissionPolicy()
        self._clock = clock

    def admit_staged(
        self,
        *,
        context: ArtifactCommandContext,
        request: AcquisitionRequest,
        staged_path: Path,
        staged_evidence: StagedPDFEvidence,
    ) -> DocumentAdmissionRecord:
        command_context = ArtifactCommandContext.model_validate(context)
        acquisition_request = AcquisitionRequest.model_validate(request)
        evidence = StagedPDFEvidence.model_validate(staged_evidence)
        if not isinstance(staged_path, Path):
            raise TypeError("staged PDF path must be a pathlib.Path")

        descriptor = ArtifactDescriptor.model_validate(
            self._artifact_store.put_file(
                staged_path,
                media_type="application/pdf",
                max_bytes=MAX_PDF_BYTES,
                context=command_context,
            )
        )
        evidence.require_matches(descriptor)

        registered = ArtifactDescriptor.model_validate(
            self._artifact_repository.register(
                context=command_context,
                descriptor=descriptor,
            )
        )
        if registered != descriptor:
            raise StagedPDFEvidenceMismatchError(
                "registered artifact differs from the immutable artifact"
            )

        duplicate_of = self._acquisition_repository.find_duplicate(
            context=command_context,
            artifact_id=descriptor.artifact_id,
        )
        if duplicate_of == acquisition_request.acquisition_id:
            duplicate_of = None

        observed_at = _require_utc_clock(self._clock())
        profile = _profile_from_evidence(
            descriptor=descriptor,
            evidence=evidence,
            inspected_at=observed_at,
        )
        decision = self._policy.evaluate(
            profile=profile,
            request=acquisition_request,
            duplicate_of_acquisition_id=duplicate_of,
        )
        record = DocumentAdmissionRecord(
            context=command_context,
            request=acquisition_request,
            artifact=descriptor,
            profile=profile,
            lifecycle=decision.lifecycle,
            outcome=decision.outcome,
            reason_codes=decision.reason_codes,
            duplicate_of_acquisition_id=decision.duplicate_of_acquisition_id,
            recorded_at=observed_at,
        )
        stored = self._acquisition_repository.record(record)
        return DocumentAdmissionRecord.model_validate(stored)


def _profile_from_evidence(
    *,
    descriptor: ArtifactDescriptor,
    evidence: StagedPDFEvidence,
    inspected_at: datetime,
) -> PDFSafetyProfile:
    header_version = _header_version(evidence.leading_bytes)
    eof_marker_present = evidence.trailing_bytes.rstrip(_PDF_TRAILING_WHITESPACE).endswith(b"%%EOF")
    return PDFSafetyProfile(
        artifact_id=descriptor.artifact_id,
        digest=descriptor.digest,
        size_bytes=descriptor.size_bytes,
        header_version=header_version,
        eof_marker_present=eof_marker_present,
        page_marker_count=None,
        mime_signature_consistency=(
            SafetyCheckState.PASS if header_version is not None else SafetyCheckState.FAIL
        ),
        size_limit=SafetyCheckState.PASS,
        page_count_limit=SafetyCheckState.UNKNOWN,
        encryption_password_state=SafetyCheckState.UNKNOWN,
        malformed_structure=(
            SafetyCheckState.UNKNOWN if eof_marker_present else SafetyCheckState.FAIL
        ),
        embedded_files=SafetyCheckState.UNKNOWN,
        active_actions=SafetyCheckState.UNKNOWN,
        suspicious_references=SafetyCheckState.UNKNOWN,
        decompression_ratio=SafetyCheckState.UNKNOWN,
        source_policy=evidence.source_policy,
        available_disk=evidence.available_disk,
        inspected_at=inspected_at,
    )


def _header_version(leading_bytes: bytes) -> str | None:
    if len(leading_bytes) != _LEADING_EVIDENCE_BYTES:
        return None
    if not leading_bytes.startswith(b"%PDF-1."):
        return None
    minor = leading_bytes[-1]
    if minor not in b"01234567":
        return None
    return f"1.{chr(minor)}"


def _require_utc_clock(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("document admission clock must return a datetime")
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("document admission clock must return timezone-aware UTC")
    return value
