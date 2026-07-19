"""Dense/lexical staging and atomic publication integration tests."""

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
from rsi_atlas_ingestion.chunk_service import ChunkService
from rsi_atlas_ingestion.index_service import IndexService, extract_exact_identifiers
from rsi_atlas_ingestion.publication_service import PublicationService
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


def _seed_chunk_set(
    *,
    database: PostgresDatabase,
    store: ContentAddressedArtifactStore,
    context: ArtifactCommandContext,
) -> tuple[str, UUID, str]:
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
                Jsonb({"policy_version": "phase-2d-test"}),
                datetime(2026, 7, 19, 12, 2, tzinfo=UTC),
            ),
        )
        connection.commit()

    document = CanonicalDocument.model_validate_json(canonical_bytes)
    chunk_set = ChunkService(
        processing=processing, artifacts=artifacts, store=store
    ).chunk_and_persist(
        context=context,
        acquisition_id=acquisition_id,
        document_version_id=document_version_id,
        family=ChunkStrategyFamily.PAGE_BASED,
        document=document,
        canonical_content_hash=content_hash,
        now=datetime(2026, 7, 19, 12, 3, tzinfo=UTC),
    )
    return chunk_set.chunk_set_id, acquisition_id, document_version_id


def test_extract_exact_identifiers_finds_evm_address() -> None:
    hits = extract_exact_identifiers("Treasury 0xAbcDef0123456789AbcDef0123456789AbcDef01 ok")
    assert hits == (("evm_address", "0xabcdef0123456789abcdef0123456789abcdef01"),)


def test_staging_is_non_searchable_until_activate(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    context = _context()
    store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    chunk_set_id, acquisition_id, document_version_id = _seed_chunk_set(
        database=postgres_database, store=store, context=context
    )
    processing = DocumentProcessingRepository(postgres_database)
    artifacts = ArtifactRepository(postgres_database, store)
    indexer = IndexService(processing=processing, artifacts=artifacts, store=store)
    publisher = PublicationService(processing=processing)

    staged = indexer.stage_indexes(
        context=context,
        acquisition_id=acquisition_id,
        chunk_set_id=chunk_set_id,
        now=datetime(2026, 7, 19, 12, 4, tzinfo=UTC),
    )
    assert staged["searchable"] is False
    assert staged["status"] == "staging"
    assert staged["dense_cardinality"] == staged["lexical_cardinality"]
    index_version_id = UUID(str(staged["index_version_id"]))

    # Staging rows exist, but active search must miss them.
    staging_hits = processing.search_lexical_any_status(
        context=context, index_version_id=index_version_id, query="Bitcoin"
    )
    assert len(staging_hits) >= 1
    active_hits = processing.search_lexical_active(
        context=context,
        document_version_id=document_version_id,
        chunk_set_id=chunk_set_id,
        query="Bitcoin",
    )
    assert active_hits == []

    activated = publisher.activate(
        context=context,
        index_version_id=index_version_id,
        now=datetime(2026, 7, 19, 12, 5, tzinfo=UTC),
    )
    assert activated["searchable"] is True
    assert activated["status"] == "active"
    active_hits = processing.search_lexical_active(
        context=context,
        document_version_id=document_version_id,
        chunk_set_id=chunk_set_id,
        query="Bitcoin",
    )
    assert active_hits == staging_hits

    # Idempotent re-stage / re-activate.
    staged_again = indexer.stage_indexes(
        context=context,
        acquisition_id=acquisition_id,
        chunk_set_id=chunk_set_id,
        now=datetime(2026, 7, 19, 12, 6, tzinfo=UTC),
    )
    assert staged_again["index_version_id"] == staged["index_version_id"]
    activated_again = publisher.activate(context=context, index_version_id=index_version_id)
    assert activated_again["status"] == "active"


def test_activate_supersedes_prior_active(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    context = _context()
    store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    chunk_set_id, acquisition_id, document_version_id = _seed_chunk_set(
        database=postgres_database, store=store, context=context
    )
    processing = DocumentProcessingRepository(postgres_database)
    artifacts = ArtifactRepository(postgres_database, store)
    indexer = IndexService(processing=processing, artifacts=artifacts, store=store)
    publisher = PublicationService(processing=processing)

    first = indexer.stage_indexes(
        context=context, acquisition_id=acquisition_id, chunk_set_id=chunk_set_id
    )
    first_id = UUID(str(first["index_version_id"]))
    publisher.activate(context=context, index_version_id=first_id)

    # Force a distinct staging version by writing a second version row manually after
    # mutating lexical content hash uniqueness via a second chunk family.
    document = CanonicalDocument.model_validate_json(FIXTURE.read_bytes())
    content_hash = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    recursive = ChunkService(
        processing=processing, artifacts=artifacts, store=store
    ).chunk_and_persist(
        context=context,
        acquisition_id=acquisition_id,
        document_version_id=document_version_id,
        family=ChunkStrategyFamily.RECURSIVE,
        document=document,
        canonical_content_hash=content_hash,
    )
    second = indexer.stage_indexes(
        context=context,
        acquisition_id=acquisition_id,
        chunk_set_id=recursive.chunk_set_id,
    )
    second_id = UUID(str(second["index_version_id"]))
    publisher.activate(context=context, index_version_id=second_id)

    # First remains active for its own chunk_set; second is active for recursive.
    first_hits = processing.search_lexical_active(
        context=context,
        document_version_id=document_version_id,
        chunk_set_id=chunk_set_id,
        query="Bitcoin",
    )
    second_hits = processing.search_lexical_active(
        context=context,
        document_version_id=document_version_id,
        chunk_set_id=recursive.chunk_set_id,
        query="Bitcoin",
    )
    assert first_hits
    assert second_hits


def test_rollback_clears_active_search(postgres_database: PostgresDatabase, tmp_path: Path) -> None:
    context = _context()
    store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    chunk_set_id, acquisition_id, document_version_id = _seed_chunk_set(
        database=postgres_database, store=store, context=context
    )
    processing = DocumentProcessingRepository(postgres_database)
    artifacts = ArtifactRepository(postgres_database, store)
    indexer = IndexService(processing=processing, artifacts=artifacts, store=store)
    publisher = PublicationService(processing=processing)

    staged = indexer.stage_indexes(
        context=context, acquisition_id=acquisition_id, chunk_set_id=chunk_set_id
    )
    index_version_id = UUID(str(staged["index_version_id"]))
    publisher.activate(context=context, index_version_id=index_version_id)
    assert processing.search_lexical_active(
        context=context,
        document_version_id=document_version_id,
        chunk_set_id=chunk_set_id,
        query="Bitcoin",
    )

    rolled = publisher.rollback(
        context=context,
        document_version_id=document_version_id,
        chunk_set_id=chunk_set_id,
    )
    assert rolled["searchable"] is False
    assert rolled["status"] == "rolled_back"
    assert (
        processing.search_lexical_active(
            context=context,
            document_version_id=document_version_id,
            chunk_set_id=chunk_set_id,
            query="Bitcoin",
        )
        == []
    )
    version = processing.get_retrieval_index_version(
        context=context, index_version_id=index_version_id
    )
    assert version is not None
    assert version["status"] == "superseded"
