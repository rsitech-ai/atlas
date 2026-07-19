"""DocumentProcessingService admission gate + preflight-before-parse composition."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
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
    PDFSafetyProfile,
    SafetyCheckState,
)
from rsi_atlas_contracts.document_parsing import AdmissionAssessmentDraft
from rsi_atlas_ingestion.canonical_service import CanonicalizationService
from rsi_atlas_ingestion.parser_benchmark import qualify_development_candidate
from rsi_atlas_ingestion.parser_service import ParserService
from rsi_atlas_ingestion.preflight_service import (
    PreflightService,
    _assessment_from_profile,
    _bind_preflight_profile,
)
from rsi_atlas_ingestion.processing_pipeline import (
    DocumentProcessingService,
    admission_allows_development_processing,
    assessment_allows_development_parse,
)
from rsi_atlas_storage import (
    AcquisitionRepository,
    ArtifactRepository,
    ContentAddressedArtifactStore,
    DatabaseSettings,
    DocumentProcessingRepository,
    MigrationRunner,
    PostgresDatabase,
)


@pytest.fixture(scope="session")
def postgres_database() -> Iterator[PostgresDatabase]:
    database = PostgresDatabase(
        DatabaseSettings.from_conninfo(os.environ["RSI_ATLAS_TEST_DATABASE_URL"])
    )
    MigrationRunner(database, Path("migrations")).apply_all()
    yield database


def _context() -> ArtifactCommandContext:
    return ArtifactCommandContext(
        tenant_id=uuid4(),
        workspace_id=uuid4(),
        actor_id=uuid4(),
        trace_id=uuid4(),
    )


def _record(
    *,
    context: ArtifactCommandContext,
    descriptor: ArtifactDescriptor,
    acquisition_id: UUID,
    outcome: AdmissionOutcome,
    lifecycle: DocumentLifecycle,
) -> DocumentAdmissionRecord:
    return DocumentAdmissionRecord(
        context=context,
        request=AcquisitionRequest(
            acquisition_id=acquisition_id,
            method=AcquisitionMethod.MANUAL_CLI,
            original_filename="doc.pdf",
            source_locator=f"manual-import:{acquisition_id}",
            declared_media_type="application/pdf",
            collector_version="atlas-cli-0.1.0",
            network_profile=NetworkProfile.OFFLINE,
        ),
        artifact=descriptor,
        profile=PDFSafetyProfile(
            artifact_id=descriptor.artifact_id,
            digest=descriptor.digest,
            size_bytes=descriptor.size_bytes,
            header_version="1.7",
            eof_marker_present=True,
            page_marker_count=1,
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
            inspected_at=datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        ),
        lifecycle=lifecycle,
        outcome=outcome,
        reason_codes=("required_check_unknown",),
        recorded_at=datetime(2026, 7, 19, 12, 1, tzinfo=UTC),
    )


def _service(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> tuple[DocumentProcessingService, AcquisitionRepository, ContentAddressedArtifactStore]:
    store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    artifacts = ArtifactRepository(postgres_database, store)
    admissions = AcquisitionRepository(postgres_database)
    processing = DocumentProcessingRepository(postgres_database)
    service = DocumentProcessingService(
        admissions=admissions,
        processing=processing,
        artifacts=artifacts,
        store=store,
        preflight=PreflightService(admissions=admissions, processing=processing),
        parser=ParserService(admissions=admissions, processing=processing),
        canonicalizer=CanonicalizationService(
            admissions=admissions,
            processing=processing,
            artifacts=artifacts,
            store=store,
        ),
        run_root=tmp_path / "processing",
    )
    return service, admissions, store


def test_admission_gate_helpers() -> None:
    assert admission_allows_development_processing(AdmissionOutcome.QUARANTINE_FOR_REVIEW)
    assert not admission_allows_development_processing(AdmissionOutcome.REQUEST_PASSWORD)
    assert not admission_allows_development_processing(AdmissionOutcome.REJECT_UNSAFE)
    assert not admission_allows_development_processing(AdmissionOutcome.MARK_EXACT_DUPLICATE)


def test_assessment_blocks_password_and_embedded() -> None:
    context = _context()
    artifact = ArtifactDescriptor(
        artifact_id=ArtifactID("sha256:" + "e" * 64),
        digest="e" * 64,
        size_bytes=10,
        media_type="application/pdf",
    )
    encrypted = _bind_preflight_profile(
        context=context,
        acquisition_id=uuid4(),
        artifact=artifact,
        evidence={
            "page_count": None,
            "pages": [],
            "encryption_password_state": "fail",
            "malformed_structure": "unknown",
            "embedded_files": "unknown",
            "active_actions": "unknown",
            "suspicious_references": "unknown",
            "decompression_ratio": "unknown",
            "decoded_stream_bytes": 0,
            "character_count": 0,
            "image_only_page_count": None,
            "warnings": ["password_required_or_encrypted"],
        },
    )
    draft = _assessment_from_profile(
        context=context,
        acquisition_id=encrypted.acquisition_id,
        artifact=artifact,
        prior_admission_hash="f" * 64,
        profile=encrypted,
    )
    assert isinstance(draft, AdmissionAssessmentDraft)
    assert not assessment_allows_development_parse(draft)


def test_start_blocks_rejected_admission_without_parse(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    service, admissions, store = _service(postgres_database, tmp_path)
    context = _context()
    fixture = Path("packages/ingestion/benchmarks/pdf/fixtures/audit_mixed_font.pdf")
    descriptor = store.put_bytes(
        fixture.read_bytes(), media_type="application/pdf", context=context
    )
    ArtifactRepository(postgres_database, store).register(context=context, descriptor=descriptor)
    acquisition_id = uuid4()
    admissions.record(
        _record(
            context=context,
            descriptor=descriptor,
            acquisition_id=acquisition_id,
            outcome=AdmissionOutcome.REJECT_UNSAFE,
            lifecycle=DocumentLifecycle.REJECTED,
        )
    )
    status = service.start(context=context, acquisition_id=acquisition_id)
    assert status.state == "failed"
    assert status.failure_code == "admission_not_processable"
    attempts = postgres_database.fetch_value(
        """
        SELECT count(*) FROM atlas_ingestion.document_parser_attempts
        WHERE tenant_id = %s AND workspace_id = %s AND acquisition_id = %s
        """,
        (context.tenant_id, context.workspace_id, acquisition_id),
    )
    assert attempts == 0


def test_start_runs_preflight_then_parse_for_quarantine(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    qualify_development_candidate()
    service, admissions, store = _service(postgres_database, tmp_path)
    context = _context()
    fixture = Path("packages/ingestion/benchmarks/pdf/fixtures/audit_mixed_font.pdf")
    descriptor = store.put_bytes(
        fixture.read_bytes(), media_type="application/pdf", context=context
    )
    ArtifactRepository(postgres_database, store).register(context=context, descriptor=descriptor)
    acquisition_id = uuid4()
    admissions.record(
        _record(
            context=context,
            descriptor=descriptor,
            acquisition_id=acquisition_id,
            outcome=AdmissionOutcome.QUARANTINE_FOR_REVIEW,
            lifecycle=DocumentLifecycle.AWAITING_REVIEW,
        )
    )
    status = service.start(context=context, acquisition_id=acquisition_id)
    assert status.state == "canonicalized"
    assert status.document_version_id is not None
    preflight_attempts = postgres_database.fetch_value(
        """
        SELECT count(*) FROM atlas_ingestion.document_parser_attempts
        WHERE tenant_id = %s AND workspace_id = %s AND acquisition_id = %s
          AND operation = 'preflight'
        """,
        (context.tenant_id, context.workspace_id, acquisition_id),
    )
    parse_attempts = postgres_database.fetch_value(
        """
        SELECT count(*) FROM atlas_ingestion.document_parser_attempts
        WHERE tenant_id = %s AND workspace_id = %s AND acquisition_id = %s
          AND operation = 'parse'
        """,
        (context.tenant_id, context.workspace_id, acquisition_id),
    )
    assert preflight_attempts == 1
    assert parse_attempts == 1


def test_start_blocks_encrypted_after_preflight(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    service, admissions, store = _service(postgres_database, tmp_path)
    context = _context()
    fixture = Path("packages/ingestion/benchmarks/pdf/fixtures/encrypted_password.pdf")
    descriptor = store.put_bytes(
        fixture.read_bytes(), media_type="application/pdf", context=context
    )
    ArtifactRepository(postgres_database, store).register(context=context, descriptor=descriptor)
    acquisition_id = uuid4()
    admissions.record(
        _record(
            context=context,
            descriptor=descriptor,
            acquisition_id=acquisition_id,
            outcome=AdmissionOutcome.QUARANTINE_FOR_REVIEW,
            lifecycle=DocumentLifecycle.AWAITING_REVIEW,
        )
    )
    status = service.start(context=context, acquisition_id=acquisition_id)
    assert status.state == "review_required"
    assert status.failure_code == "preflight_password_required"
    parse_attempts = postgres_database.fetch_value(
        """
        SELECT count(*) FROM atlas_ingestion.document_parser_attempts
        WHERE tenant_id = %s AND workspace_id = %s AND acquisition_id = %s
          AND operation = 'parse'
        """,
        (context.tenant_id, context.workspace_id, acquisition_id),
    )
    assert parse_attempts == 0
