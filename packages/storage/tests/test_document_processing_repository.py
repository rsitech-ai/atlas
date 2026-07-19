from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
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
from rsi_atlas_storage import (
    AcquisitionRepository,
    ArtifactRepository,
    ContentAddressedArtifactStore,
    DatabaseSettings,
    MigrationRunner,
    PostgresDatabase,
)
from rsi_atlas_storage.document_processing_repository import (
    AttemptEventKind,
    AttemptOperation,
    DocumentProcessingRepository,
    binding_hash,
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


def _admit(database: PostgresDatabase, tmp_path: Path, context: ArtifactCommandContext):
    store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    descriptor = store.put_bytes(
        b"%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n",
        media_type="application/pdf",
        context=context,
    )
    ArtifactRepository(database, store).register(context=context, descriptor=descriptor)
    acquisition_id = uuid4()
    record = DocumentAdmissionRecord(
        context=context,
        request=AcquisitionRequest(
            acquisition_id=acquisition_id,
            method=AcquisitionMethod.MANUAL_CLI,
            original_filename="evidence.pdf",
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
            inspected_at=datetime(2026, 7, 19, 10, 0, tzinfo=UTC),
        ),
        lifecycle=DocumentLifecycle.AWAITING_REVIEW,
        outcome=AdmissionOutcome.QUARANTINE_FOR_REVIEW,
        reason_codes=("required_check_unknown",),
        recorded_at=datetime(2026, 7, 19, 10, 1, tzinfo=UTC),
    )
    AcquisitionRepository(database).record(record)
    return descriptor, acquisition_id


def test_binding_hash_is_stable() -> None:
    acquisition_id = uuid4()
    first = binding_hash(
        acquisition_id=acquisition_id,
        artifact_id="artifact:abc",
        operation=AttemptOperation.PREFLIGHT,
        configuration_hash="a" * 64,
    )
    second = binding_hash(
        acquisition_id=acquisition_id,
        artifact_id="artifact:abc",
        operation=AttemptOperation.PREFLIGHT,
        configuration_hash="a" * 64,
    )
    assert first == second


def test_start_finish_and_reconcile_attempt_journal(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    context = _context()
    descriptor, acquisition_id = _admit(postgres_database, tmp_path, context)
    repo = DocumentProcessingRepository(postgres_database)
    attempt = repo.start_attempt(
        context=context,
        acquisition_id=acquisition_id,
        artifact_id=str(descriptor.artifact_id),
        operation=AttemptOperation.PREFLIGHT,
        configuration_hash="b" * 64,
    )
    assert (
        repo.start_attempt(
            context=context,
            acquisition_id=acquisition_id,
            artifact_id=str(descriptor.artifact_id),
            operation=AttemptOperation.PREFLIGHT,
            configuration_hash="b" * 64,
            attempt_id=attempt.attempt_id,
            now=attempt.created_at,
        )
        == attempt
    )

    repo.finish_attempt(
        context=context,
        attempt_id=attempt.attempt_id,
        event_kind=AttemptEventKind.SUCCEEDED,
        payload={"status": "ok"},
    )
    repo.finish_attempt(
        context=context,
        attempt_id=attempt.attempt_id,
        event_kind=AttemptEventKind.SUCCEEDED,
        payload={"status": "ok"},
    )

    abandoned_context = _context()
    abandoned_root = tmp_path / "abandoned"
    abandoned_root.mkdir()
    abandoned_descriptor, abandoned_acquisition = _admit(
        postgres_database, abandoned_root, abandoned_context
    )
    abandoned = repo.start_attempt(
        context=abandoned_context,
        acquisition_id=abandoned_acquisition,
        artifact_id=str(abandoned_descriptor.artifact_id),
        operation=AttemptOperation.PREFLIGHT,
        configuration_hash="c" * 64,
        now=datetime.now(UTC) - timedelta(hours=2),
    )
    closed = repo.reconcile_abandoned(
        context=abandoned_context,
        older_than=datetime.now(UTC) - timedelta(hours=1),
    )
    assert closed == 1
    assert abandoned.attempt_id is not None
