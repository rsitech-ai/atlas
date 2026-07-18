import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from rsi_atlas_contracts import (
    AcquisitionMethod,
    AdmissionOutcome,
    ArtifactDescriptor,
    ArtifactID,
    DocumentAdmissionRecord,
    DocumentLifecycle,
    PDFSafetyProfile,
    SafetyCheckState,
)
from rsi_atlas_engine.api import create_app
from rsi_atlas_engine.import_staging import ImportStagingArea
from rsi_atlas_ingestion import StagedPDFEvidence
from rsi_atlas_storage import AcquisitionConflictError


class FakeAdmissionService:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def admit_staged(self, **call: Any) -> DocumentAdmissionRecord:
        self.calls.append(call)
        if self.error is not None:
            raise self.error
        evidence: StagedPDFEvidence = call["staged_evidence"]
        request = call["request"]
        context = call["context"]
        digest = evidence.digest
        descriptor = ArtifactDescriptor(
            artifact_id=ArtifactID(f"sha256:{digest}"),
            digest=digest,
            size_bytes=evidence.size_bytes,
            media_type="application/pdf",
        )
        profile = PDFSafetyProfile(
            artifact_id=descriptor.artifact_id,
            digest=digest,
            size_bytes=evidence.size_bytes,
            header_version="1.7",
            eof_marker_present=True,
            page_marker_count=None,
            mime_signature_consistency=SafetyCheckState.PASS,
            size_limit=SafetyCheckState.PASS,
            page_count_limit=SafetyCheckState.UNKNOWN,
            encryption_password_state=SafetyCheckState.UNKNOWN,
            malformed_structure=SafetyCheckState.UNKNOWN,
            embedded_files=SafetyCheckState.UNKNOWN,
            active_actions=SafetyCheckState.UNKNOWN,
            suspicious_references=SafetyCheckState.UNKNOWN,
            decompression_ratio=SafetyCheckState.UNKNOWN,
            source_policy=SafetyCheckState.PASS,
            available_disk=SafetyCheckState.PASS,
            inspected_at=datetime(2026, 7, 18, 21, 10, tzinfo=UTC),
        )
        return DocumentAdmissionRecord(
            context=context,
            request=request,
            artifact=descriptor,
            profile=profile,
            lifecycle=DocumentLifecycle.AWAITING_REVIEW,
            outcome=AdmissionOutcome.QUARANTINE_FOR_REVIEW,
            reason_codes=("required_check_unknown",),
            recorded_at=datetime(2026, 7, 18, 21, 10, tzinfo=UTC),
        )


def _headers(payload: bytes) -> dict[str, str]:
    return {
        "content-type": "application/pdf",
        "content-length": str(len(payload)),
        "x-rsi-tenant-id": str(UUID("11111111-1111-4111-8111-111111111111")),
        "x-rsi-actor-id": str(UUID("33333333-3333-4333-8333-333333333333")),
        "x-rsi-trace-id": str(UUID("44444444-4444-4444-8444-444444444444")),
        "x-rsi-acquisition-id": str(UUID("55555555-5555-4555-8555-555555555555")),
    }


def _url(workspace_id: UUID | None = None) -> str:
    workspace = workspace_id or UUID("22222222-2222-4222-8222-222222222222")
    return (
        f"/v1/workspaces/{workspace}/documents:admit"
        "?filename=protocol-paper.pdf&method=manual_native&collector_version=native-0.1.0"
    )


def _client(tmp_path: Path, service: FakeAdmissionService) -> tuple[TestClient, Path]:
    staging_root = tmp_path / "staging"
    staging_root.mkdir(mode=0o700)
    staging_root.chmod(0o700)
    app = create_app(
        document_admission_service=service,
        import_staging_area=ImportStagingArea(staging_root),
    )
    return TestClient(app), staging_root


def test_admission_endpoint_streams_raw_pdf_and_returns_strict_record(tmp_path: Path) -> None:
    payload = b"%PDF-1.7\n/Type /Page\ncontent\n%%EOF\n"
    service = FakeAdmissionService()
    client, staging_root = _client(tmp_path, service)

    response = client.post(_url(), headers=_headers(payload), content=payload)

    assert response.status_code == 200
    record = DocumentAdmissionRecord.model_validate(response.json())
    assert record.outcome is AdmissionOutcome.QUARANTINE_FOR_REVIEW
    assert record.artifact.digest == hashlib.sha256(payload).hexdigest()
    assert len(service.calls) == 1
    call = service.calls[0]
    assert call["staged_evidence"].leading_bytes == payload[:8]
    assert call["staged_evidence"].trailing_bytes == payload[-1024:]
    assert call["request"].method is AcquisitionMethod.MANUAL_NATIVE
    assert call["request"].original_filename == "protocol-paper.pdf"
    assert call["context"].workspace_id == UUID("22222222-2222-4222-8222-222222222222")
    assert tuple(staging_root.iterdir()) == ()


def test_endpoint_rejects_oversized_declared_body_before_service(tmp_path: Path) -> None:
    service = FakeAdmissionService()
    client, staging_root = _client(tmp_path, service)
    headers = _headers(b"x")
    headers["content-length"] = "33554433"

    response = client.post(_url(), headers=headers, content=b"")

    assert response.status_code == 413
    assert service.calls == []
    assert tuple(staging_root.iterdir()) == ()


def test_endpoint_requires_explicit_content_length(tmp_path: Path) -> None:
    payload = b"%PDF-1.7\n%%EOF\n"
    service = FakeAdmissionService()
    client, staging_root = _client(tmp_path, service)
    headers = _headers(payload)
    headers.pop("content-length")

    response = client.post(_url(), headers=headers, content=iter((payload,)))

    assert response.status_code == 411
    assert service.calls == []
    assert tuple(staging_root.iterdir()) == ()


def test_endpoint_rejects_body_longer_than_declared_and_cleans_staging(tmp_path: Path) -> None:
    service = FakeAdmissionService()
    client, staging_root = _client(tmp_path, service)
    payload = b"%PDF-1.7\n%%EOF\n"
    headers = _headers(payload)
    headers["content-length"] = str(len(payload) - 1)

    response = client.post(_url(), headers=headers, content=payload)

    assert response.status_code == 400
    assert service.calls == []
    assert tuple(staging_root.iterdir()) == ()


def test_endpoint_rejects_wrong_content_type_and_invalid_identity(tmp_path: Path) -> None:
    service = FakeAdmissionService()
    client, _ = _client(tmp_path, service)
    payload = b"%PDF-1.7\n%%EOF\n"
    wrong_type = _headers(payload)
    wrong_type["content-type"] = "text/plain"
    invalid_identity = _headers(payload)
    invalid_identity["x-rsi-actor-id"] = "not-a-uuid"

    assert client.post(_url(), headers=wrong_type, content=payload).status_code == 415
    assert client.post(_url(), headers=invalid_identity, content=payload).status_code == 422
    assert service.calls == []


def test_endpoint_rejects_cli_method_and_unsafe_filename(tmp_path: Path) -> None:
    service = FakeAdmissionService()
    client, _ = _client(tmp_path, service)
    payload = b"%PDF-1.7\n%%EOF\n"
    cli_url = _url().replace("manual_native", "manual_cli")
    unsafe_url = _url().replace("protocol-paper.pdf", "..%2Fpaper.pdf")

    assert client.post(cli_url, headers=_headers(payload), content=payload).status_code == 422
    assert client.post(unsafe_url, headers=_headers(payload), content=payload).status_code == 422
    assert service.calls == []


def test_endpoint_maps_acquisition_conflict_and_cleans_staging(tmp_path: Path) -> None:
    payload = b"%PDF-1.7\n%%EOF\n"
    service = FakeAdmissionService(error=AcquisitionConflictError("different evidence"))
    client, staging_root = _client(tmp_path, service)

    response = client.post(_url(), headers=_headers(payload), content=payload)

    assert response.status_code == 409
    assert response.json() == {"detail": "Acquisition identity already names different evidence."}
    assert len(service.calls) == 1
    assert tuple(staging_root.iterdir()) == ()


def test_endpoint_maps_persistence_failure_to_sanitized_503(tmp_path: Path) -> None:
    payload = b"%PDF-1.7\n%%EOF\n"
    service = FakeAdmissionService(error=RuntimeError("password=secret host=/private/db"))
    client, staging_root = _client(tmp_path, service)

    response = client.post(_url(), headers=_headers(payload), content=payload)

    assert response.status_code == 503
    assert response.json() == {"detail": "Document admission is temporarily unavailable."}
    assert "secret" not in response.text
    assert "/private" not in response.text
    assert tuple(staging_root.iterdir()) == ()


def test_endpoint_rejects_missing_or_duplicate_identity_header(tmp_path: Path) -> None:
    payload = b"%PDF-1.7\n%%EOF\n"
    service = FakeAdmissionService()
    client, staging_root = _client(tmp_path, service)
    missing = _headers(payload)
    missing.pop("x-rsi-trace-id")
    duplicate = list(_headers(payload).items())
    duplicate.append(("x-rsi-trace-id", "66666666-6666-4666-8666-666666666666"))

    assert client.post(_url(), headers=missing, content=payload).status_code == 422
    assert client.post(_url(), headers=duplicate, content=payload).status_code == 422
    assert service.calls == []
    assert tuple(staging_root.iterdir()) == ()
