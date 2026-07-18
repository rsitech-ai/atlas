import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb
from rsi_atlas_contracts import (
    AcquisitionMethod,
    AcquisitionRequest,
    AdmissionOutcome,
    ArtifactCommandContext,
    ArtifactDescriptor,
    DocumentAdmissionRecord,
    DocumentLifecycle,
    NetworkProfile,
    PDFSafetyProfile,
    SafetyCheckState,
)
from rsi_atlas_storage import (
    AcquisitionConflictError,
    AcquisitionRepository,
    ArtifactRepository,
    ContentAddressedArtifactStore,
    DatabaseSettings,
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


def _context(*, workspace_id: object | None = None) -> ArtifactCommandContext:
    return ArtifactCommandContext(
        tenant_id=uuid4(),
        workspace_id=workspace_id or uuid4(),
        actor_id=uuid4(),
        trace_id=uuid4(),
    )


def _request(*, acquisition_id: object | None = None) -> AcquisitionRequest:
    identity = acquisition_id or uuid4()
    return AcquisitionRequest(
        acquisition_id=identity,
        method=AcquisitionMethod.MANUAL_CLI,
        original_filename="evidence.pdf",
        source_locator=f"manual-import:{identity}",
        declared_media_type="application/pdf",
        collector_version="atlas-cli-0.1.0",
        network_profile=NetworkProfile.OFFLINE,
    )


def _profile(descriptor: ArtifactDescriptor) -> PDFSafetyProfile:
    return PDFSafetyProfile(
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
        inspected_at=datetime(2026, 7, 18, 20, 50, tzinfo=UTC),
    )


def _record(
    *,
    context: ArtifactCommandContext,
    descriptor: ArtifactDescriptor,
    request: AcquisitionRequest | None = None,
    recorded_at: datetime | None = None,
    **changes: Any,
) -> DocumentAdmissionRecord:
    values: dict[str, Any] = {
        "context": context,
        "request": request or _request(),
        "artifact": descriptor,
        "profile": _profile(descriptor),
        "lifecycle": DocumentLifecycle.AWAITING_REVIEW,
        "outcome": AdmissionOutcome.QUARANTINE_FOR_REVIEW,
        "reason_codes": ("required_check_unknown",),
        "recorded_at": recorded_at or datetime(2026, 7, 18, 20, 51, tzinfo=UTC),
    }
    values.update(changes)
    return DocumentAdmissionRecord(**values)


def _registered_artifact(
    database: PostgresDatabase,
    tmp_path: Path,
    context: ArtifactCommandContext,
    *,
    payload: bytes = b"%PDF-1.7\n/Type /Page\n%%EOF\n",
) -> tuple[ContentAddressedArtifactStore, ArtifactDescriptor]:
    store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    descriptor = store.put_bytes(payload, media_type="application/pdf", context=context)
    ArtifactRepository(database, store).register(context=context, descriptor=descriptor)
    return store, descriptor


def test_record_round_trip_is_scoped_and_emits_one_outbox_event(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    context = _context()
    _, descriptor = _registered_artifact(postgres_database, tmp_path, context)
    repository = AcquisitionRepository(postgres_database)
    record = _record(context=context, descriptor=descriptor)

    stored = repository.record(record)

    assert stored == record
    assert repository.find(context=context, acquisition_id=record.request.acquisition_id) == record
    assert postgres_database.fetch_one(
        """
        SELECT event_type, payload->>'schema_version'
        FROM atlas_ingestion.outbox_events
        WHERE tenant_id = %s AND workspace_id = %s AND acquisition_id = %s
        """,
        (context.tenant_id, context.workspace_id, record.request.acquisition_id),
    ) == ("DocumentAdmissionRecorded", "1.0.0")


def test_exact_replay_returns_one_acquisition_decision_and_event(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    context = _context()
    _, descriptor = _registered_artifact(postgres_database, tmp_path, context)
    repository = AcquisitionRepository(postgres_database)
    record = _record(context=context, descriptor=descriptor)

    assert repository.record(record) == record
    assert repository.record(record) == record

    assert postgres_database.fetch_one(
        """
        SELECT
          (SELECT count(*) FROM atlas_ingestion.document_acquisitions
           WHERE tenant_id = %s AND workspace_id = %s AND acquisition_id = %s),
          (SELECT count(*) FROM atlas_ingestion.document_admission_decisions
           WHERE tenant_id = %s AND workspace_id = %s AND acquisition_id = %s),
          (SELECT count(*) FROM atlas_ingestion.outbox_events
           WHERE tenant_id = %s AND workspace_id = %s AND acquisition_id = %s)
        """,
        (
            context.tenant_id,
            context.workspace_id,
            record.request.acquisition_id,
            context.tenant_id,
            context.workspace_id,
            record.request.acquisition_id,
            context.tenant_id,
            context.workspace_id,
            record.request.acquisition_id,
        ),
    ) == (1, 1, 1)


def test_reusing_acquisition_identity_for_different_evidence_fails(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    context = _context()
    store, first_descriptor = _registered_artifact(postgres_database, tmp_path, context)
    second_descriptor = store.put_bytes(
        b"%PDF-1.7\n/Type /Page\nchanged\n%%EOF\n",
        media_type="application/pdf",
        context=context,
    )
    ArtifactRepository(postgres_database, store).register(
        context=context, descriptor=second_descriptor
    )
    repository = AcquisitionRepository(postgres_database)
    request = _request()
    repository.record(_record(context=context, descriptor=first_descriptor, request=request))

    with pytest.raises(AcquisitionConflictError, match="different evidence"):
        repository.record(_record(context=context, descriptor=second_descriptor, request=request))


def test_second_same_workspace_artifact_becomes_an_explicit_duplicate(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    context = _context()
    _, descriptor = _registered_artifact(postgres_database, tmp_path, context)
    repository = AcquisitionRepository(postgres_database)
    first = repository.record(_record(context=context, descriptor=descriptor))

    second = repository.record(
        _record(
            context=context,
            descriptor=descriptor,
            recorded_at=first.recorded_at + timedelta(seconds=1),
        )
    )

    assert second.lifecycle is DocumentLifecycle.DUPLICATE
    assert second.outcome is AdmissionOutcome.MARK_EXACT_DUPLICATE
    assert second.reason_codes == ("exact_duplicate",)
    assert second.duplicate_of_acquisition_id == first.request.acquisition_id
    assert postgres_database.fetch_one(
        """
        SELECT duplicate_of_acquisition_id
        FROM atlas_ingestion.document_duplicate_links
        WHERE tenant_id = %s AND workspace_id = %s AND acquisition_id = %s
        """,
        (context.tenant_id, context.workspace_id, second.request.acquisition_id),
    ) == (first.request.acquisition_id,)


def test_concurrent_same_artifact_creates_one_primary_and_one_duplicate(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    context = _context()
    _, descriptor = _registered_artifact(postgres_database, tmp_path, context)
    repository = AcquisitionRepository(postgres_database)
    records = (
        _record(context=context, descriptor=descriptor),
        _record(
            context=context,
            descriptor=descriptor,
            recorded_at=datetime(2026, 7, 18, 20, 51, 1, tzinfo=UTC),
        ),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(repository.record, records))

    assert {result.outcome for result in results} == {
        AdmissionOutcome.QUARANTINE_FOR_REVIEW,
        AdmissionOutcome.MARK_EXACT_DUPLICATE,
    }
    assert sum(result.duplicate_of_acquisition_id is not None for result in results) == 1


def test_identical_artifact_in_another_workspace_is_not_a_duplicate(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    first_context = _context()
    store, descriptor = _registered_artifact(postgres_database, tmp_path, first_context)
    second_context = _context()
    ArtifactRepository(postgres_database, store).register(
        context=second_context, descriptor=descriptor
    )
    repository = AcquisitionRepository(postgres_database)

    first = repository.record(_record(context=first_context, descriptor=descriptor))
    second = repository.record(_record(context=second_context, descriptor=descriptor))

    assert first.outcome is AdmissionOutcome.QUARANTINE_FOR_REVIEW
    assert second.outcome is AdmissionOutcome.QUARANTINE_FOR_REVIEW
    assert second.duplicate_of_acquisition_id is None


def test_find_never_crosses_workspace_scope(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    context = _context()
    _, descriptor = _registered_artifact(postgres_database, tmp_path, context)
    repository = AcquisitionRepository(postgres_database)
    record = repository.record(_record(context=context, descriptor=descriptor))

    assert (
        repository.find(
            context=_context(),
            acquisition_id=record.request.acquisition_id,
        )
        is None
    )


def test_database_rejects_an_inconsistent_outcome_lifecycle_pair(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    context = _context()
    _, descriptor = _registered_artifact(postgres_database, tmp_path, context)
    record = _record(context=context, descriptor=descriptor)
    invalid_acquisition_id = uuid4()
    invalid_request = _request(acquisition_id=invalid_acquisition_id)

    with (
        postgres_database.connect() as connection,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        connection.execute(
            """
            INSERT INTO atlas_ingestion.document_acquisitions (
                tenant_id, workspace_id, acquisition_id, artifact_id, actor_id, trace_id,
                request, profile, recorded_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                context.tenant_id,
                context.workspace_id,
                invalid_acquisition_id,
                str(descriptor.artifact_id),
                context.actor_id,
                context.trace_id,
                Jsonb(invalid_request.model_dump(mode="json")),
                Jsonb(record.profile.model_dump(mode="json")),
                record.recorded_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO atlas_ingestion.document_admission_decisions (
                tenant_id, workspace_id, acquisition_id, lifecycle, outcome,
                reason_codes, duplicate_of_acquisition_id, record, recorded_at
            ) VALUES (%s, %s, %s, 'rejected', 'quarantine_for_review', %s, NULL, %s, %s)
            """,
            (
                context.tenant_id,
                context.workspace_id,
                invalid_acquisition_id,
                Jsonb(["required_check_unknown"]),
                Jsonb(record.model_dump(mode="json")),
                record.recorded_at,
            ),
        )


@pytest.mark.parametrize(
    "table",
    (
        "document_acquisitions",
        "document_admission_decisions",
        "document_duplicate_links",
        "outbox_events",
    ),
)
def test_admission_evidence_tables_reject_update_delete_and_truncate(
    postgres_database: PostgresDatabase, tmp_path: Path, table: str
) -> None:
    context = _context()
    _, descriptor = _registered_artifact(postgres_database, tmp_path, context)
    repository = AcquisitionRepository(postgres_database)
    first = repository.record(_record(context=context, descriptor=descriptor))
    repository.record(
        _record(
            context=context,
            descriptor=descriptor,
            recorded_at=first.recorded_at + timedelta(seconds=1),
        )
    )

    with (
        postgres_database.connect() as connection,
        pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState),
    ):
        connection.execute(f"UPDATE atlas_ingestion.{table} SET recorded_at = recorded_at")
    with (
        postgres_database.connect() as connection,
        pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState),
    ):
        connection.execute(f"DELETE FROM atlas_ingestion.{table}")
    with (
        postgres_database.connect() as connection,
        pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState),
    ):
        connection.execute(f"TRUNCATE atlas_ingestion.{table} CASCADE")
