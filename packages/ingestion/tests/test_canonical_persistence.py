"""Canonical persistence integration tests."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from rsi_atlas_contracts import (
    AcquisitionMethod,
    AcquisitionRequest,
    AdmissionOutcome,
    ArtifactCommandContext,
    DocumentAdmissionRecord,
    DocumentLifecycle,
    NetworkProfile,
    PDFSafetyProfile,
    SafetyCheckState,
)
from rsi_atlas_document_worker.parsers import PyPdfParserCandidate
from rsi_atlas_ingestion.canonical_service import CanonicalizationService
from rsi_atlas_ingestion.canonicalization import CanonicalizationError
from rsi_atlas_storage import (
    AcquisitionRepository,
    ArtifactRepository,
    ContentAddressedArtifactStore,
    DatabaseSettings,
    DocumentProcessingRepository,
    MigrationRunner,
    PostgresDatabase,
)
from rsi_atlas_storage.document_processing_repository import (
    AttemptEventKind,
    AttemptOperation,
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


def test_canonical_persist_is_idempotent_and_history_preserving(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    context = _context()
    store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    fixture = Path("packages/ingestion/benchmarks/pdf/fixtures/audit_mixed_font.pdf")
    descriptor = store.put_bytes(
        fixture.read_bytes(), media_type="application/pdf", context=context
    )
    artifacts = ArtifactRepository(postgres_database, store)
    artifacts.register(context=context, descriptor=descriptor)
    acquisition_id = uuid4()
    record = DocumentAdmissionRecord(
        context=context,
        request=AcquisitionRequest(
            acquisition_id=acquisition_id,
            method=AcquisitionMethod.MANUAL_CLI,
            original_filename="audit.pdf",
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
        lifecycle=DocumentLifecycle.AWAITING_REVIEW,
        outcome=AdmissionOutcome.QUARANTINE_FOR_REVIEW,
        reason_codes=("required_check_unknown",),
        recorded_at=datetime(2026, 7, 19, 12, 1, tzinfo=UTC),
    )
    admissions = AcquisitionRepository(postgres_database)
    admissions.record(record)
    processing = DocumentProcessingRepository(postgres_database)
    attempt = processing.start_attempt(
        context=context,
        acquisition_id=acquisition_id,
        artifact_id=str(descriptor.artifact_id),
        operation=AttemptOperation.PARSE,
        configuration_hash="a" * 64,
    )
    processing.finish_attempt(
        context=context,
        attempt_id=attempt.attempt_id,
        event_kind=AttemptEventKind.SUCCEEDED,
        payload={"status": "ok"},
    )
    fd = os.open(fixture, os.O_RDONLY)
    try:
        parse_result = PyPdfParserCandidate().parse(artifact_fd=fd)
    finally:
        os.close(fd)

    service = CanonicalizationService(
        admissions=admissions,
        processing=processing,
        artifacts=artifacts,
        store=store,
    )
    benchmark_hash = hashlib.sha256(b"phase-2b-dev-benchmark").hexdigest()
    first = service.canonicalize_and_persist(
        context=context,
        acquisition_id=acquisition_id,
        parse_attempt_id=attempt.attempt_id,
        parse_result=parse_result,
        benchmark_hash=benchmark_hash,
        now=datetime(2026, 7, 19, 12, 2, tzinfo=UTC),
    )
    second = service.canonicalize_and_persist(
        context=context,
        acquisition_id=acquisition_id,
        parse_attempt_id=attempt.attempt_id,
        parse_result=parse_result,
        benchmark_hash=benchmark_hash,
        now=datetime(2026, 7, 19, 12, 2, tzinfo=UTC),
    )
    assert first.document_version_id == second.document_version_id
    assert first.canonical_content_hash == second.canonical_content_hash
    loaded = service.load_canonical_document(
        context=context, document_version_id=first.document_version_id
    )
    assert loaded.canonical_json_bytes() == first.canonical_document.canonical_json_bytes()

    # Corrupt CAS payload fails retrieval.
    payload_path = store.payload_path(first.canonical_artifact.artifact_id)
    payload_path.write_bytes(b"corrupt")
    with pytest.raises(CanonicalizationError):
        service.load_canonical_document(
            context=context, document_version_id=first.document_version_id
        )
