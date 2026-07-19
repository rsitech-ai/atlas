"""Integration tests for active-only hybrid retrieval."""

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
    EvidencePacket,
    NetworkProfile,
    PDFSafetyProfile,
    QueryFamily,
    ResearchQuery,
    RetrievalAbstention,
    SafetyCheckState,
)
from rsi_atlas_ingestion.chunk_service import ChunkService
from rsi_atlas_ingestion.embedding import DeterministicEmbedder
from rsi_atlas_ingestion.index_service import IndexService
from rsi_atlas_ingestion.publication_service import PublicationService
from rsi_atlas_retrieval import HybridRetrievalService
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


def _seed_published(
    *,
    database: PostgresDatabase,
    store: ContentAddressedArtifactStore,
    context: ArtifactCommandContext,
) -> tuple[str, str]:
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
                Jsonb({"policy_version": "phase-3-test"}),
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
    staged = IndexService(processing=processing, artifacts=artifacts, store=store).stage_indexes(
        context=context,
        acquisition_id=acquisition_id,
        chunk_set_id=chunk_set.chunk_set_id,
    )
    PublicationService(processing=processing).activate(
        context=context,
        index_version_id=UUID(str(staged["index_version_id"])),
    )
    return chunk_set.chunk_set_id, document_version_id


def test_hybrid_retrieve_returns_packet_from_active_publication(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    context = _context()
    store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    chunk_set_id, document_version_id = _seed_published(
        database=postgres_database, store=store, context=context
    )
    processing = DocumentProcessingRepository(postgres_database)
    embedder = DeterministicEmbedder()
    service = HybridRetrievalService(processing=processing, embed_text=embedder.embed_text)
    query = ResearchQuery(
        context=context,
        query_id=uuid4(),
        text="Bitcoin network research unlock",
        document_version_ids=(document_version_id,),
        chunk_set_ids=(chunk_set_id,),
        as_of=datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        query_family=QueryFamily.NARRATIVE_EXPLANATION,
        latency_budget_ms=5_000,
        context_budget_tokens=2_048,
    )
    result = service.retrieve(query=query)
    assert isinstance(result, EvidencePacket)
    assert result.items
    assert result.items[0].component_ranks
    plan = service.build_default_plan(query=query)
    replay = service.build_replay_record(query=query, plan=plan, result=result)
    assert replay.packet_id == result.packet_id


def test_hybrid_retrieve_abstains_without_active_publication(
    postgres_database: PostgresDatabase,
) -> None:
    context = _context()
    processing = DocumentProcessingRepository(postgres_database)
    embedder = DeterministicEmbedder()
    service = HybridRetrievalService(processing=processing, embed_text=embedder.embed_text)
    query = ResearchQuery(
        context=context,
        query_id=uuid4(),
        text="missing evidence question",
        document_version_ids=("canonical:" + ("1" * 64),),
        chunk_set_ids=("chunkset:" + ("2" * 64),),
        as_of=datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        query_family=QueryFamily.NARRATIVE_EXPLANATION,
        latency_budget_ms=5_000,
        context_budget_tokens=2_048,
    )
    result = service.retrieve(query=query)
    assert isinstance(result, RetrievalAbstention)
    assert result.reason
