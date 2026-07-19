"""Chunk set CAS + PostgreSQL persistence integration tests."""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from psycopg.types.json import Jsonb
from rsi_atlas_contracts import (
    AcquisitionMethod,
    AcquisitionRequest,
    AdmissionOutcome,
    ArtifactCommandContext,
    CanonicalDocument,
    ChunkStrategyFamily,
    DocumentAdmissionRecord,
    DocumentLifecycle,
    NetworkProfile,
    PDFSafetyProfile,
    SafetyCheckState,
)
from rsi_atlas_ingestion.chunk_service import ChunkPersistenceError, ChunkService
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

FIXTURE = Path("packages/ingestion/benchmarks/chunking/fixtures/crypto_two_page_canonical.json")


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


def _seed_canonical(
    *,
    database: PostgresDatabase,
    store: ContentAddressedArtifactStore,
    context: ArtifactCommandContext,
) -> tuple[str, str, UUID]:
    """Admission + parse attempt + canonical version bound to the frozen fixture."""
    pdf_bytes = b"%PDF-1.4 minimal seed\n%%EOF\n"
    pdf = store.put_bytes(pdf_bytes, media_type="application/pdf", context=context)
    artifacts = ArtifactRepository(database, store)
    artifacts.register(context=context, descriptor=pdf)

    acquisition_id = uuid4()
    record = DocumentAdmissionRecord(
        context=context,
        request=AcquisitionRequest(
            acquisition_id=acquisition_id,
            method=AcquisitionMethod.MANUAL_CLI,
            original_filename="seed.pdf",
            source_locator=f"manual-import:{acquisition_id}",
            declared_media_type="application/pdf",
            collector_version="atlas-cli-0.1.0",
            network_profile=NetworkProfile.OFFLINE,
        ),
        artifact=pdf,
        profile=PDFSafetyProfile(
            artifact_id=pdf.artifact_id,
            digest=pdf.digest,
            size_bytes=pdf.size_bytes,
            header_version="1.4",
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
    AcquisitionRepository(database).record(record)
    processing = DocumentProcessingRepository(database)
    attempt = processing.start_attempt(
        context=context,
        acquisition_id=acquisition_id,
        artifact_id=str(pdf.artifact_id),
        operation=AttemptOperation.PARSE,
        configuration_hash="a" * 64,
    )
    processing.finish_attempt(
        context=context,
        attempt_id=attempt.attempt_id,
        event_kind=AttemptEventKind.SUCCEEDED,
        payload={"status": "ok"},
    )

    canonical_bytes = FIXTURE.read_bytes()
    content_hash = hashlib.sha256(canonical_bytes).hexdigest()
    document_version_id = f"canonical:{content_hash}"
    canonical = store.put_bytes(
        canonical_bytes,
        media_type="application/vnd.rsi-atlas.canonical+json",
        context=context,
    )
    artifacts.register(context=context, descriptor=canonical)
    with database.connect() as connection:
        connection.execute(
            """
            INSERT INTO atlas_ingestion.canonical_document_versions (
                tenant_id, workspace_id, document_version_id, manifest_id,
                acquisition_id, parse_attempt_id, artifact_id, canonical_artifact_id,
                canonical_content_hash, parser_configuration_hash,
                manifest, qualification, recorded_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                context.tenant_id,
                context.workspace_id,
                document_version_id,
                uuid4(),
                acquisition_id,
                attempt.attempt_id,
                str(pdf.artifact_id),
                str(canonical.artifact_id),
                content_hash,
                "e" * 64,
                Jsonb(
                    {
                        "document_version_id": document_version_id,
                        "canonical_content_hash": content_hash,
                        "canonical_artifact": canonical.model_dump(mode="json"),
                    }
                ),
                Jsonb({"policy_version": "phase-2c-test"}),
                datetime(2026, 7, 19, 12, 2, tzinfo=UTC),
            ),
        )
        connection.commit()
    return document_version_id, content_hash, acquisition_id


def test_chunk_persist_is_idempotent_and_lists_five_families(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    context = _context()
    store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    document_version_id, content_hash, acquisition_id = _seed_canonical(
        database=postgres_database, store=store, context=context
    )
    document = CanonicalDocument.model_validate_json(FIXTURE.read_bytes())
    processing = DocumentProcessingRepository(postgres_database)
    artifacts = ArtifactRepository(postgres_database, store)
    service = ChunkService(processing=processing, artifacts=artifacts, store=store)

    first = service.chunk_all_implemented(
        context=context,
        acquisition_id=acquisition_id,
        document_version_id=document_version_id,
        document=document,
        canonical_content_hash=content_hash,
        now=datetime(2026, 7, 19, 12, 3, tzinfo=UTC),
    )
    second = service.chunk_all_implemented(
        context=context,
        acquisition_id=acquisition_id,
        document_version_id=document_version_id,
        document=document,
        canonical_content_hash=content_hash,
        now=datetime(2026, 7, 19, 12, 3, tzinfo=UTC),
    )
    assert len(first) == 5
    assert [item.chunk_set_id for item in first] == [item.chunk_set_id for item in second]

    listed = processing.list_chunk_sets(context=context, document_version_id=document_version_id)
    assert len(listed) == 5
    assert {row["strategy_id"] for row in listed} == {
        "fixed_token",
        "recursive",
        "page_based",
        "parent_child",
        "table_aware",
    }

    loaded = service.load_chunk_set(context=context, chunk_set_id=first[0].chunk_set_id)
    assert loaded.canonical_json_bytes() == first[0].canonical_json_bytes()

    row = processing.get_chunk_set_manifest(context=context, chunk_set_id=first[0].chunk_set_id)
    assert row is not None
    artifact_id = row["chunk_set_artifact"]["artifact_id"]
    store.payload_path(artifact_id).write_bytes(b"corrupt")
    with pytest.raises(ChunkPersistenceError):
        service.load_chunk_set(context=context, chunk_set_id=first[0].chunk_set_id)


def test_single_family_persist_round_trip(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    context = _context()
    store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    document_version_id, content_hash, acquisition_id = _seed_canonical(
        database=postgres_database, store=store, context=context
    )
    document = CanonicalDocument.model_validate_json(FIXTURE.read_bytes())
    service = ChunkService(
        processing=DocumentProcessingRepository(postgres_database),
        artifacts=ArtifactRepository(postgres_database, store),
        store=store,
    )
    chunk_set = service.chunk_and_persist(
        context=context,
        acquisition_id=acquisition_id,
        document_version_id=document_version_id,
        family=ChunkStrategyFamily.PAGE_BASED,
        document=document,
        canonical_content_hash=content_hash,
    )
    assert chunk_set.strategy.family is ChunkStrategyFamily.PAGE_BASED
    assert chunk_set.quality.chunk_count == 2
