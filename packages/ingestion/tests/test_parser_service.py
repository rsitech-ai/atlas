from __future__ import annotations

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
from rsi_atlas_ingestion.parser_benchmark import qualify_development_candidate
from rsi_atlas_ingestion.parser_service import ParserService
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


def test_parser_service_persists_started_and_terminal_events(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    qualify_development_candidate()
    context = _context()
    store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    fixture = Path("packages/ingestion/benchmarks/pdf/fixtures/audit_mixed_font.pdf")
    descriptor = store.put_bytes(
        fixture.read_bytes(), media_type="application/pdf", context=context
    )
    ArtifactRepository(postgres_database, store).register(context=context, descriptor=descriptor)
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
            inspected_at=datetime(2026, 7, 19, 11, 0, tzinfo=UTC),
        ),
        lifecycle=DocumentLifecycle.AWAITING_REVIEW,
        outcome=AdmissionOutcome.QUARANTINE_FOR_REVIEW,
        reason_codes=("required_check_unknown",),
        recorded_at=datetime(2026, 7, 19, 11, 1, tzinfo=UTC),
    )
    admissions = AcquisitionRepository(postgres_database)
    admissions.record(record)
    processing = DocumentProcessingRepository(postgres_database)
    service = ParserService(admissions=admissions, processing=processing)
    staged = tmp_path / "staged.pdf"
    staged.write_bytes(fixture.read_bytes())
    result = service.run(
        context=context,
        acquisition_id=acquisition_id,
        artifact_path=staged,
        run_root=tmp_path / "runs",
    )
    assert result["parse_result"]["status"] == "succeeded"
    assert result["qualified_candidate"]["candidate"] == "pypdf"
    count = postgres_database.fetch_value(
        """
        SELECT count(*) FROM atlas_ingestion.document_parser_attempt_events
        WHERE tenant_id = %s AND workspace_id = %s AND attempt_id = %s
        """,
        (context.tenant_id, context.workspace_id, result["attempt_id"]),
    )
    assert count == 2
