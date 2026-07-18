import hashlib
import socket
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from rsi_atlas_contracts import (
    AcquisitionMethod,
    AcquisitionRequest,
    AdmissionOutcome,
    ArtifactCommandContext,
    ArtifactDescriptor,
    ArtifactID,
    DocumentAdmissionRecord,
    DocumentLifecycle,
    NetworkProfile,
    SafetyCheckState,
)
from rsi_atlas_ingestion import (
    DocumentAdmissionService,
    PDFAdmissionPolicy,
    StagedPDFEvidence,
    StagedPDFEvidenceMismatchError,
)
from rsi_atlas_storage import ContentAddressedArtifactStore

NOW = datetime(2026, 7, 18, 22, 30, tzinfo=UTC)
DEFAULT_ACQUISITION_ID = UUID("55555555-5555-4555-8555-555555555555")
CONTEXT = ArtifactCommandContext(
    tenant_id=UUID("11111111-1111-4111-8111-111111111111"),
    workspace_id=UUID("22222222-2222-4222-8222-222222222222"),
    actor_id=UUID("33333333-3333-4333-8333-333333333333"),
    trace_id=UUID("44444444-4444-4444-8444-444444444444"),
)


class RecordingArtifactRepository:
    def __init__(self, *, failure: BaseException | None = None) -> None:
        self.failure = failure
        self.calls: list[tuple[ArtifactCommandContext, ArtifactDescriptor]] = []

    def register(
        self, *, context: ArtifactCommandContext, descriptor: ArtifactDescriptor
    ) -> ArtifactDescriptor:
        self.calls.append((context, descriptor))
        if self.failure is not None:
            raise self.failure
        return descriptor


class RecordingAcquisitionRepository:
    def __init__(
        self,
        *,
        duplicate_of: UUID | None = None,
        failure: BaseException | None = None,
        stored_result: Callable[[DocumentAdmissionRecord], DocumentAdmissionRecord] | None = None,
    ) -> None:
        self.duplicate_of = duplicate_of
        self.failure = failure
        self.stored_result = stored_result or (lambda record: record)
        self.duplicate_calls: list[tuple[ArtifactCommandContext, ArtifactID]] = []
        self.record_calls: list[DocumentAdmissionRecord] = []

    def find_duplicate(
        self, *, context: ArtifactCommandContext, artifact_id: ArtifactID
    ) -> UUID | None:
        self.duplicate_calls.append((context, artifact_id))
        return self.duplicate_of

    def record(self, record: DocumentAdmissionRecord) -> DocumentAdmissionRecord:
        self.record_calls.append(record)
        if self.failure is not None:
            raise self.failure
        return self.stored_result(record)


def _request(
    acquisition_id: UUID = DEFAULT_ACQUISITION_ID,
) -> AcquisitionRequest:
    return AcquisitionRequest(
        acquisition_id=acquisition_id,
        method=AcquisitionMethod.MANUAL_CLI,
        original_filename="evidence.pdf",
        source_locator=f"manual-import:{acquisition_id}",
        declared_media_type="application/pdf",
        collector_version="atlas-cli-0.1.0",
        network_profile=NetworkProfile.OFFLINE,
    )


def _pdf(*, header: bytes = b"%PDF-1.7", eof: bytes = b"%%EOF\n") -> bytes:
    return header + b"\n1 0 obj\n<< /Type /Catalog >>\nendobj\n" + eof


def _evidence(payload: bytes, **changes: Any) -> StagedPDFEvidence:
    values: dict[str, Any] = {
        "digest": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "leading_bytes": payload[:8],
        "trailing_bytes": payload[-1024:],
        "source_policy": SafetyCheckState.PASS,
        "available_disk": SafetyCheckState.PASS,
    }
    values.update(changes)
    return StagedPDFEvidence(**values)


def _staged_pdf(tmp_path: Path, payload: bytes) -> Path:
    path = tmp_path / "staged.pdf"
    path.write_bytes(payload)
    path.chmod(0o600)
    return path


def _service(
    tmp_path: Path,
    *,
    artifact_repository: RecordingArtifactRepository | None = None,
    acquisition_repository: RecordingAcquisitionRepository | None = None,
    clock: Callable[[], datetime] = lambda: NOW,
) -> tuple[
    DocumentAdmissionService,
    ContentAddressedArtifactStore,
    RecordingArtifactRepository,
    RecordingAcquisitionRepository,
]:
    store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    artifact_repository = artifact_repository or RecordingArtifactRepository()
    acquisition_repository = acquisition_repository or RecordingAcquisitionRepository()
    return (
        DocumentAdmissionService(
            artifact_store=store,
            artifact_repository=artifact_repository,
            acquisition_repository=acquisition_repository,
            policy=PDFAdmissionPolicy(),
            clock=clock,
        ),
        store,
        artifact_repository,
        acquisition_repository,
    )


def test_service_publishes_raw_before_conservative_review_decision(tmp_path: Path) -> None:
    payload = _pdf()
    staged_path = _staged_pdf(tmp_path, payload)
    service, store, artifacts, acquisitions = _service(tmp_path)

    result = service.admit_staged(
        context=CONTEXT,
        request=_request(),
        staged_path=staged_path,
        staged_evidence=_evidence(payload),
    )

    assert result.lifecycle is DocumentLifecycle.AWAITING_REVIEW
    assert result.outcome is AdmissionOutcome.QUARANTINE_FOR_REVIEW
    assert result.reason_codes == ("required_check_unknown",)
    assert result.profile.mime_signature_consistency is SafetyCheckState.PASS
    assert result.profile.size_limit is SafetyCheckState.PASS
    assert result.profile.malformed_structure is SafetyCheckState.UNKNOWN
    assert result.profile.page_count_limit is SafetyCheckState.UNKNOWN
    assert result.profile.embedded_files is SafetyCheckState.UNKNOWN
    assert result.profile.active_actions is SafetyCheckState.UNKNOWN
    assert result.profile.suspicious_references is SafetyCheckState.UNKNOWN
    assert result.profile.decompression_ratio is SafetyCheckState.UNKNOWN
    assert result.profile.encryption_password_state is SafetyCheckState.UNKNOWN
    assert result.profile.header_version == "1.7"
    assert result.profile.eof_marker_present is True
    assert result.profile.page_marker_count is None
    assert result.profile.inspected_at == NOW
    assert result.recorded_at == NOW
    assert store.verify(result.artifact.artifact_id, context=CONTEXT) == result.artifact
    assert artifacts.calls == [(CONTEXT, result.artifact)]
    assert acquisitions.record_calls == [result]


def test_invalid_header_is_authoritative_unsafe_failure(tmp_path: Path) -> None:
    payload = _pdf(header=b"NOT-PDF!")
    staged_path = _staged_pdf(tmp_path, payload)
    service, _, _, _ = _service(tmp_path)

    result = service.admit_staged(
        context=CONTEXT,
        request=_request(),
        staged_path=staged_path,
        staged_evidence=_evidence(payload),
    )

    assert result.profile.header_version is None
    assert result.profile.mime_signature_consistency is SafetyCheckState.FAIL
    assert result.outcome is AdmissionOutcome.REJECT_UNSAFE
    assert result.reason_codes == ("pdf_signature_or_mime_invalid",)


def test_missing_terminal_eof_is_authoritative_structure_failure(tmp_path: Path) -> None:
    payload = _pdf(eof=b"missing-eof\n")
    staged_path = _staged_pdf(tmp_path, payload)
    service, _, _, _ = _service(tmp_path)

    result = service.admit_staged(
        context=CONTEXT,
        request=_request(),
        staged_path=staged_path,
        staged_evidence=_evidence(payload),
    )

    assert result.profile.eof_marker_present is False
    assert result.profile.malformed_structure is SafetyCheckState.FAIL
    assert result.outcome is AdmissionOutcome.QUARANTINE_FOR_REVIEW
    assert result.reason_codes == ("malformed_structure",)


def test_same_workspace_digest_is_recorded_as_exact_duplicate(tmp_path: Path) -> None:
    payload = _pdf()
    staged_path = _staged_pdf(tmp_path, payload)
    primary_id = UUID("66666666-6666-4666-8666-666666666666")
    repository = RecordingAcquisitionRepository(duplicate_of=primary_id)
    service, _, _, _ = _service(tmp_path, acquisition_repository=repository)

    result = service.admit_staged(
        context=CONTEXT,
        request=_request(),
        staged_path=staged_path,
        staged_evidence=_evidence(payload),
    )

    assert result.lifecycle is DocumentLifecycle.DUPLICATE
    assert result.outcome is AdmissionOutcome.MARK_EXACT_DUPLICATE
    assert result.reason_codes == ("exact_duplicate",)
    assert result.duplicate_of_acquisition_id == primary_id
    assert repository.duplicate_calls == [(CONTEXT, result.artifact.artifact_id)]


def test_idempotent_retry_does_not_identify_itself_as_duplicate(tmp_path: Path) -> None:
    payload = _pdf()
    staged_path = _staged_pdf(tmp_path, payload)
    request = _request()
    repository = RecordingAcquisitionRepository(duplicate_of=request.acquisition_id)
    service, _, _, _ = _service(tmp_path, acquisition_repository=repository)

    result = service.admit_staged(
        context=CONTEXT,
        request=request,
        staged_path=staged_path,
        staged_evidence=_evidence(payload),
    )

    assert result.outcome is AdmissionOutcome.QUARANTINE_FOR_REVIEW
    assert result.duplicate_of_acquisition_id is None


def test_service_returns_strict_repository_result(tmp_path: Path) -> None:
    payload = _pdf()
    staged_path = _staged_pdf(tmp_path, payload)
    stored: list[DocumentAdmissionRecord] = []

    def remember(record: DocumentAdmissionRecord) -> DocumentAdmissionRecord:
        stored.append(record)
        return record

    repository = RecordingAcquisitionRepository(stored_result=remember)
    service, _, _, _ = _service(tmp_path, acquisition_repository=repository)

    result = service.admit_staged(
        context=CONTEXT,
        request=_request(),
        staged_path=staged_path,
        staged_evidence=_evidence(payload),
    )

    assert result is stored[0]


def test_evidence_mismatch_fails_after_raw_publication_without_registration(
    tmp_path: Path,
) -> None:
    payload = _pdf()
    staged_path = _staged_pdf(tmp_path, payload)
    service, store, artifacts, acquisitions = _service(tmp_path)
    digest = hashlib.sha256(payload).hexdigest()

    with pytest.raises(StagedPDFEvidenceMismatchError, match="immutable artifact"):
        service.admit_staged(
            context=CONTEXT,
            request=_request(),
            staged_path=staged_path,
            staged_evidence=_evidence(payload, digest="f" * 64),
        )

    descriptor = store.verify(ArtifactID(f"sha256:{digest}"), context=CONTEXT)
    assert descriptor.size_bytes == len(payload)
    assert artifacts.calls == []
    assert acquisitions.record_calls == []


@pytest.mark.parametrize("window", ("leading", "trailing"))
def test_forged_evidence_window_fails_against_immutable_cas_bytes(
    tmp_path: Path,
    window: str,
) -> None:
    payload = _pdf(header=b"NOT-PDF!", eof=b"missing-eof\n")
    staged_path = _staged_pdf(tmp_path, payload)
    service, store, artifacts, acquisitions = _service(tmp_path)
    changes = (
        {"leading_bytes": b"%PDF-1.7"}
        if window == "leading"
        else {"trailing_bytes": b"x" * (len(payload) - 6) + b"%%EOF\n"}
    )

    with pytest.raises(StagedPDFEvidenceMismatchError, match="evidence window"):
        service.admit_staged(
            context=CONTEXT,
            request=_request(),
            staged_path=staged_path,
            staged_evidence=_evidence(payload, **changes),
        )

    digest = hashlib.sha256(payload).hexdigest()
    assert store.read_bytes(ArtifactID(f"sha256:{digest}"), context=CONTEXT) == payload
    assert artifacts.calls == []
    assert acquisitions.record_calls == []


@pytest.mark.parametrize("failure_boundary", ("artifact_database", "policy", "acquisition"))
def test_raw_cas_bytes_remain_when_a_later_boundary_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_boundary: str
) -> None:
    payload = _pdf()
    staged_path = _staged_pdf(tmp_path, payload)
    artifact_repository = RecordingArtifactRepository(
        failure=RuntimeError("database unavailable")
        if failure_boundary == "artifact_database"
        else None
    )
    acquisition_repository = RecordingAcquisitionRepository(
        failure=RuntimeError("database unavailable") if failure_boundary == "acquisition" else None
    )
    service, store, _, _ = _service(
        tmp_path,
        artifact_repository=artifact_repository,
        acquisition_repository=acquisition_repository,
    )
    if failure_boundary == "policy":

        def fail_policy(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("policy unavailable")

        monkeypatch.setattr(PDFAdmissionPolicy, "evaluate", fail_policy)

    with pytest.raises(RuntimeError, match="unavailable"):
        service.admit_staged(
            context=CONTEXT,
            request=_request(),
            staged_path=staged_path,
            staged_evidence=_evidence(payload),
        )

    digest = hashlib.sha256(payload).hexdigest()
    descriptor = store.verify(ArtifactID(f"sha256:{digest}"), context=CONTEXT)
    assert descriptor.size_bytes == len(payload)
    assert store.read_bytes(descriptor.artifact_id, context=CONTEXT) == payload


def test_staged_evidence_is_strict_and_exactly_bounded() -> None:
    payload = _pdf()
    evidence = _evidence(payload)

    with pytest.raises(ValidationError):
        StagedPDFEvidence.model_validate({**evidence.model_dump(), "unexpected": True})
    with pytest.raises(ValidationError, match="leading bytes"):
        _evidence(payload, leading_bytes=payload[:7])
    with pytest.raises(ValidationError, match="trailing bytes"):
        _evidence(payload, trailing_bytes=payload[-4:])
    with pytest.raises(ValidationError):
        _evidence(payload, size_bytes="52")


def test_staged_file_must_be_owner_private(tmp_path: Path) -> None:
    payload = _pdf()
    staged_path = _staged_pdf(tmp_path, payload)
    staged_path.chmod(0o644)
    service, _, artifacts, acquisitions = _service(tmp_path)

    with pytest.raises(RuntimeError, match="owner-private"):
        service.admit_staged(
            context=CONTEXT,
            request=_request(),
            staged_path=staged_path,
            staged_evidence=_evidence(payload),
        )

    assert artifacts.calls == []
    assert acquisitions.record_calls == []


def test_clock_must_return_timezone_aware_utc_after_raw_publication(tmp_path: Path) -> None:
    payload = _pdf()
    staged_path = _staged_pdf(tmp_path, payload)
    service, store, _, acquisitions = _service(
        tmp_path, clock=lambda: datetime(2026, 7, 18, 22, 30)
    )

    with pytest.raises(ValueError, match="UTC"):
        service.admit_staged(
            context=CONTEXT,
            request=_request(),
            staged_path=staged_path,
            staged_evidence=_evidence(payload),
        )

    digest = hashlib.sha256(payload).hexdigest()
    assert store.read_bytes(ArtifactID(f"sha256:{digest}"), context=CONTEXT) == payload
    assert acquisitions.record_calls == []


def test_service_performs_no_network_subprocess_or_parser_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("forbidden boundary used")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    payload = _pdf()
    staged_path = _staged_pdf(tmp_path, payload)
    service, _, _, _ = _service(tmp_path)

    result = service.admit_staged(
        context=CONTEXT,
        request=_request(),
        staged_path=staged_path,
        staged_evidence=_evidence(payload),
    )

    assert result.outcome is AdmissionOutcome.QUARANTINE_FOR_REVIEW
