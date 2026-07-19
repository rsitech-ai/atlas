"""Append-only document processing attempt journal and assessment persistence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Jsonb
from pydantic import Field
from rsi_atlas_contracts import ArtifactCommandContext, RetrievalPublicationManifestDraft
from rsi_atlas_contracts.chunking import ChunkSetManifest
from rsi_atlas_contracts.document_parsing import CanonicalDocumentManifest
from rsi_atlas_contracts.system_status import StrictModel

from rsi_atlas_storage.database import PostgresDatabase, Row


class DocumentProcessingConflictError(RuntimeError):
    """Raised when an attempt identity is reused with divergent bindings."""


class DocumentProcessingIntegrityError(RuntimeError):
    """Raised when durable processing representations disagree."""


class AttemptOperation(StrEnum):
    PREFLIGHT = "preflight"
    PARSE = "parse"


class AttemptEventKind(StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    KILLED = "killed"
    CANCELLED = "cancelled"
    INVALID_OUTPUT = "invalid_output"
    ABANDONED = "abandoned"


_TERMINAL = frozenset(
    {
        AttemptEventKind.SUCCEEDED,
        AttemptEventKind.FAILED,
        AttemptEventKind.TIMED_OUT,
        AttemptEventKind.KILLED,
        AttemptEventKind.CANCELLED,
        AttemptEventKind.INVALID_OUTPUT,
        AttemptEventKind.ABANDONED,
    }
)


class DocumentParserAttempt(StrictModel):
    attempt_id: UUID
    acquisition_id: UUID
    artifact_id: str = Field(min_length=1, max_length=256)
    operation: AttemptOperation
    configuration_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_binding_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    actor_id: UUID
    trace_id: UUID
    created_at: datetime


def binding_hash(
    *,
    acquisition_id: UUID,
    artifact_id: str,
    operation: AttemptOperation,
    configuration_hash: str,
) -> str:
    payload = {
        "acquisition_id": str(acquisition_id),
        "artifact_id": artifact_id,
        "configuration_hash": configuration_hash,
        "operation": operation.value,
    }
    return hashlib.sha256(
        (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    ).hexdigest()


class DocumentProcessingRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def start_attempt(
        self,
        *,
        context: ArtifactCommandContext,
        acquisition_id: UUID,
        artifact_id: str,
        operation: AttemptOperation,
        configuration_hash: str,
        attempt_id: UUID | None = None,
        now: datetime | None = None,
    ) -> DocumentParserAttempt:
        command = ArtifactCommandContext.model_validate(context)
        created_at = now or datetime.now(UTC)
        if created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware UTC")
        identity = attempt_id or uuid4()
        input_hash = binding_hash(
            acquisition_id=acquisition_id,
            artifact_id=artifact_id,
            operation=operation,
            configuration_hash=configuration_hash,
        )
        attempt = DocumentParserAttempt(
            attempt_id=identity,
            acquisition_id=acquisition_id,
            artifact_id=artifact_id,
            operation=operation,
            configuration_hash=configuration_hash,
            input_binding_hash=input_hash,
            actor_id=command.actor_id,
            trace_id=command.trace_id,
            created_at=created_at,
        )
        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT attempt_id, acquisition_id, artifact_id, operation, configuration_hash,
                       input_binding_hash, actor_id, trace_id, created_at
                FROM atlas_ingestion.document_parser_attempts
                WHERE tenant_id = %s AND workspace_id = %s AND attempt_id = %s
                """,
                (command.tenant_id, command.workspace_id, identity),
            ).fetchone()
            if existing is not None:
                reconstructed = _row_to_attempt(existing)
                if reconstructed != attempt:
                    raise DocumentProcessingConflictError(
                        "attempt identity already names different bindings"
                    )
                return reconstructed
            connection.execute(
                """
                INSERT INTO atlas_ingestion.document_parser_attempts (
                    tenant_id, workspace_id, attempt_id, acquisition_id, artifact_id,
                    operation, configuration_hash, input_binding_hash,
                    actor_id, trace_id, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    identity,
                    acquisition_id,
                    artifact_id,
                    operation.value,
                    configuration_hash,
                    input_hash,
                    command.actor_id,
                    command.trace_id,
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO atlas_ingestion.document_parser_attempt_events (
                    tenant_id, workspace_id, attempt_id, event_id, event_kind,
                    is_terminal, payload, recorded_at
                ) VALUES (
                    %s, %s, %s, %s, %s, false, %s, %s
                )
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    identity,
                    uuid4(),
                    AttemptEventKind.STARTED.value,
                    Jsonb({"status": "started"}),
                    created_at,
                ),
            )
            connection.commit()
        return attempt

    def finish_attempt(
        self,
        *,
        context: ArtifactCommandContext,
        attempt_id: UUID,
        event_kind: AttemptEventKind,
        payload: dict[str, Any],
        now: datetime | None = None,
    ) -> None:
        if event_kind not in _TERMINAL:
            raise ValueError("finish_attempt requires a terminal event kind")
        command = ArtifactCommandContext.model_validate(context)
        recorded_at = now or datetime.now(UTC)
        with self._database.connect() as connection:
            started = connection.execute(
                """
                SELECT 1 FROM atlas_ingestion.document_parser_attempt_events
                WHERE tenant_id = %s AND workspace_id = %s AND attempt_id = %s
                  AND event_kind = 'started'
                """,
                (command.tenant_id, command.workspace_id, attempt_id),
            ).fetchone()
            if started is None:
                raise DocumentProcessingIntegrityError(
                    "cannot finish attempt without started event"
                )
            terminal = connection.execute(
                """
                SELECT event_kind, payload FROM atlas_ingestion.document_parser_attempt_events
                WHERE tenant_id = %s AND workspace_id = %s AND attempt_id = %s
                  AND is_terminal
                """,
                (command.tenant_id, command.workspace_id, attempt_id),
            ).fetchone()
            if terminal is not None:
                same = terminal[0] == event_kind.value and dict(terminal[1]) == payload
                if same:
                    return
                raise DocumentProcessingConflictError(
                    "attempt already has a different terminal event"
                )
            connection.execute(
                """
                INSERT INTO atlas_ingestion.document_parser_attempt_events (
                    tenant_id, workspace_id, attempt_id, event_id, event_kind,
                    is_terminal, payload, recorded_at
                ) VALUES (
                    %s, %s, %s, %s, %s, true, %s, %s
                )
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    attempt_id,
                    uuid4(),
                    event_kind.value,
                    Jsonb(payload),
                    recorded_at,
                ),
            )
            connection.commit()

    def reconcile_abandoned(
        self,
        *,
        context: ArtifactCommandContext,
        older_than: datetime,
        now: datetime | None = None,
    ) -> int:
        command = ArtifactCommandContext.model_validate(context)
        recorded_at = now or datetime.now(UTC)
        closed = 0
        with self._database.connect() as connection:
            rows = connection.execute(
                """
                SELECT a.attempt_id
                FROM atlas_ingestion.document_parser_attempts a
                WHERE a.tenant_id = %s AND a.workspace_id = %s
                  AND a.created_at < %s
                  AND EXISTS (
                    SELECT 1 FROM atlas_ingestion.document_parser_attempt_events e
                    WHERE e.tenant_id = a.tenant_id AND e.workspace_id = a.workspace_id
                      AND e.attempt_id = a.attempt_id AND e.event_kind = 'started'
                  )
                  AND NOT EXISTS (
                    SELECT 1 FROM atlas_ingestion.document_parser_attempt_events e
                    WHERE e.tenant_id = a.tenant_id AND e.workspace_id = a.workspace_id
                      AND e.attempt_id = a.attempt_id AND e.is_terminal
                  )
                """,
                (command.tenant_id, command.workspace_id, older_than),
            ).fetchall()
            for row in rows:
                terminal = connection.execute(
                    """
                    SELECT 1 FROM atlas_ingestion.document_parser_attempt_events
                    WHERE tenant_id = %s AND workspace_id = %s AND attempt_id = %s AND is_terminal
                    """,
                    (command.tenant_id, command.workspace_id, row[0]),
                ).fetchone()
                if terminal is not None:
                    continue
                connection.execute(
                    """
                    INSERT INTO atlas_ingestion.document_parser_attempt_events (
                        tenant_id, workspace_id, attempt_id, event_id, event_kind,
                        is_terminal, payload, recorded_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, true, %s, %s
                    )
                    """,
                    (
                        command.tenant_id,
                        command.workspace_id,
                        row[0],
                        uuid4(),
                        AttemptEventKind.ABANDONED.value,
                        Jsonb({"status": "abandoned"}),
                        recorded_at,
                    ),
                )
                closed += 1
            connection.commit()
        return closed

    def record_assessment(
        self,
        *,
        context: ArtifactCommandContext,
        assessment_id: UUID,
        acquisition_id: UUID,
        attempt_id: UUID,
        artifact_id: str,
        prior_admission_hash: str,
        lifecycle: str,
        outcome: str,
        reason_codes: list[str],
        assessment: dict[str, Any],
        now: datetime | None = None,
    ) -> None:
        command = ArtifactCommandContext.model_validate(context)
        recorded_at = now or datetime.now(UTC)
        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT assessment FROM atlas_ingestion.document_admission_assessments
                WHERE tenant_id = %s AND workspace_id = %s AND assessment_id = %s
                """,
                (command.tenant_id, command.workspace_id, assessment_id),
            ).fetchone()
            if existing is not None:
                if dict(existing[0]) == assessment:
                    return
                raise DocumentProcessingConflictError("assessment identity conflict")
            connection.execute(
                """
                INSERT INTO atlas_ingestion.document_admission_assessments (
                    tenant_id, workspace_id, assessment_id, acquisition_id, attempt_id,
                    artifact_id, prior_admission_hash, lifecycle, outcome, reason_codes,
                    assessment, recorded_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    assessment_id,
                    acquisition_id,
                    attempt_id,
                    artifact_id,
                    prior_admission_hash,
                    lifecycle,
                    outcome,
                    Jsonb(reason_codes),
                    Jsonb(assessment),
                    recorded_at,
                ),
            )
            connection.commit()

    def commit_canonical_manifest(
        self,
        *,
        context: ArtifactCommandContext,
        manifest: CanonicalDocumentManifest,
        parse_attempt_id: UUID,
        qualification_record: dict[str, Any],
    ) -> None:
        command = ArtifactCommandContext.model_validate(context)
        payload = manifest.model_dump(mode="json")
        # Authority field is exclude=True; dump is draft-shaped and validates on read.
        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT manifest FROM atlas_ingestion.canonical_document_versions
                WHERE tenant_id = %s AND workspace_id = %s AND document_version_id = %s
                """,
                (command.tenant_id, command.workspace_id, manifest.document_version_id),
            ).fetchone()
            if existing is not None:
                prior = dict(existing[0])
                if prior.get("canonical_content_hash") == manifest.canonical_content_hash:
                    return
                raise DocumentProcessingConflictError("canonical version identity conflict")
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
                    command.tenant_id,
                    command.workspace_id,
                    manifest.document_version_id,
                    manifest.manifest_id,
                    manifest.acquisition_id,
                    parse_attempt_id,
                    str(manifest.artifact.artifact_id),
                    str(manifest.canonical_artifact.artifact_id),
                    manifest.canonical_content_hash,
                    manifest.canonical_document.candidate.configuration_hash,
                    Jsonb(payload),
                    Jsonb(qualification_record),
                    manifest.recorded_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO atlas_ingestion.canonical_lifecycle_events (
                    tenant_id, workspace_id, event_id, acquisition_id,
                    document_version_id, event_type, payload, recorded_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    uuid4(),
                    manifest.acquisition_id,
                    manifest.document_version_id,
                    "CanonicalDocumentRecorded",
                    Jsonb(
                        {
                            "document_version_id": manifest.document_version_id,
                            "canonical_content_hash": manifest.canonical_content_hash,
                            "parse_attempt_id": str(parse_attempt_id),
                        }
                    ),
                    manifest.recorded_at,
                ),
            )
            connection.commit()

    def get_canonical_manifest(
        self,
        *,
        context: ArtifactCommandContext,
        document_version_id: str,
    ) -> dict[str, Any] | None:
        command = ArtifactCommandContext.model_validate(context)
        row = self._database.fetch_one(
            """
            SELECT manifest FROM atlas_ingestion.canonical_document_versions
            WHERE tenant_id = %s AND workspace_id = %s AND document_version_id = %s
            """,
            (command.tenant_id, command.workspace_id, document_version_id),
        )
        if row is None:
            return None
        return dict(row[0])

    def list_canonical_versions(
        self,
        *,
        context: ArtifactCommandContext,
        acquisition_id: UUID,
    ) -> list[dict[str, Any]]:
        command = ArtifactCommandContext.model_validate(context)
        with self._database.connect(autocommit=True) as connection:
            rows = connection.execute(
                """
                SELECT document_version_id, canonical_content_hash, parser_configuration_hash,
                       recorded_at, manifest
                FROM atlas_ingestion.canonical_document_versions
                WHERE tenant_id = %s AND workspace_id = %s AND acquisition_id = %s
                ORDER BY recorded_at ASC
                """,
                (command.tenant_id, command.workspace_id, acquisition_id),
            ).fetchall()
        return [
            {
                "document_version_id": row[0],
                "canonical_content_hash": row[1],
                "parser_configuration_hash": row[2],
                "recorded_at": row[3],
                "manifest": dict(row[4]),
            }
            for row in rows
        ]

    def commit_chunk_set_manifest(
        self,
        *,
        context: ArtifactCommandContext,
        manifest: ChunkSetManifest,
    ) -> None:
        command = ArtifactCommandContext.model_validate(context)
        payload = manifest.model_dump(mode="json")
        strategy = manifest.chunk_set.strategy
        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT chunk_set_content_hash
                FROM atlas_ingestion.chunk_set_versions
                WHERE tenant_id = %s
                  AND workspace_id = %s
                  AND document_version_id = %s
                  AND strategy_id = %s
                  AND configuration_hash = %s
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    manifest.document_version_id,
                    strategy.strategy_id,
                    strategy.configuration_hash,
                ),
            ).fetchone()
            if existing is not None:
                if existing[0] == manifest.chunk_set_content_hash:
                    return
                raise DocumentProcessingConflictError("chunk set identity conflict")
            connection.execute(
                """
                INSERT INTO atlas_ingestion.chunk_set_versions (
                    tenant_id, workspace_id, chunk_set_id, manifest_id,
                    acquisition_id, document_version_id, strategy_id,
                    configuration_hash, chunk_set_content_hash, chunk_set_artifact_id,
                    manifest, recorded_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    manifest.chunk_set.chunk_set_id,
                    manifest.manifest_id,
                    manifest.acquisition_id,
                    manifest.document_version_id,
                    strategy.strategy_id,
                    strategy.configuration_hash,
                    manifest.chunk_set_content_hash,
                    str(manifest.chunk_set_artifact.artifact_id),
                    Jsonb(payload),
                    manifest.recorded_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO atlas_ingestion.chunk_set_lifecycle_events (
                    tenant_id, workspace_id, event_id, acquisition_id,
                    chunk_set_id, event_type, payload, recorded_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    uuid4(),
                    manifest.acquisition_id,
                    manifest.chunk_set.chunk_set_id,
                    "ChunkSetRecorded",
                    Jsonb(
                        {
                            "chunk_set_id": manifest.chunk_set.chunk_set_id,
                            "document_version_id": manifest.document_version_id,
                            "strategy_id": strategy.strategy_id,
                            "chunk_set_content_hash": manifest.chunk_set_content_hash,
                        }
                    ),
                    manifest.recorded_at,
                ),
            )
            connection.commit()

    def get_chunk_set_manifest(
        self,
        *,
        context: ArtifactCommandContext,
        chunk_set_id: str,
    ) -> dict[str, Any] | None:
        command = ArtifactCommandContext.model_validate(context)
        row = self._database.fetch_one(
            """
            SELECT manifest FROM atlas_ingestion.chunk_set_versions
            WHERE tenant_id = %s AND workspace_id = %s AND chunk_set_id = %s
            """,
            (command.tenant_id, command.workspace_id, chunk_set_id),
        )
        if row is None:
            return None
        return dict(row[0])

    def list_chunk_sets(
        self,
        *,
        context: ArtifactCommandContext,
        document_version_id: str,
    ) -> list[dict[str, Any]]:
        command = ArtifactCommandContext.model_validate(context)
        with self._database.connect(autocommit=True) as connection:
            rows = connection.execute(
                """
                SELECT chunk_set_id, strategy_id, configuration_hash,
                       chunk_set_content_hash, recorded_at, manifest
                FROM atlas_ingestion.chunk_set_versions
                WHERE tenant_id = %s
                  AND workspace_id = %s
                  AND document_version_id = %s
                ORDER BY strategy_id ASC, recorded_at ASC
                """,
                (command.tenant_id, command.workspace_id, document_version_id),
            ).fetchall()
        return [
            {
                "chunk_set_id": row[0],
                "strategy_id": row[1],
                "configuration_hash": row[2],
                "chunk_set_content_hash": row[3],
                "recorded_at": row[4],
                "manifest": dict(row[5]),
            }
            for row in rows
        ]

    def stage_retrieval_index(
        self,
        *,
        context: ArtifactCommandContext,
        acquisition_id: UUID,
        document_version_id: str,
        chunk_set_id: str,
        chunk_set_content_hash: str,
        embedding_model_id: str,
        embedding_configuration_hash: str,
        dense_rows: list[dict[str, object]],
        lexical_rows: list[dict[str, object]],
        exact_rows: list[dict[str, object]],
        dense_content_hash: str,
        lexical_content_hash: str,
        exact_content_hash: str,
        dense_artifact_id: str,
        lexical_artifact_id: str,
        manifest: RetrievalPublicationManifestDraft,
        recorded_at: datetime,
    ) -> UUID:
        command = ArtifactCommandContext.model_validate(context)
        draft = RetrievalPublicationManifestDraft.model_validate(manifest)
        index_version_id = uuid4()
        with self._database.connect() as connection:
            existing = connection.execute(
                """
                SELECT index_version_id
                FROM atlas_ingestion.retrieval_index_versions
                WHERE tenant_id = %s
                  AND workspace_id = %s
                  AND chunk_set_id = %s
                  AND embedding_configuration_hash = %s
                  AND dense_content_hash = %s
                  AND lexical_content_hash = %s
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    chunk_set_id,
                    embedding_configuration_hash,
                    dense_content_hash,
                    lexical_content_hash,
                ),
            ).fetchone()
            if existing is not None:
                return UUID(str(existing[0]))

            connection.execute(
                """
                INSERT INTO atlas_ingestion.retrieval_index_versions (
                    tenant_id, workspace_id, index_version_id, acquisition_id,
                    document_version_id, chunk_set_id, chunk_set_content_hash,
                    embedding_model_id, embedding_configuration_hash, status,
                    dense_cardinality, lexical_cardinality, exact_identifier_cardinality,
                    dense_content_hash, lexical_content_hash, exact_content_hash,
                    dense_index_artifact_id, lexical_index_artifact_id, recorded_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, 'staging',
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    index_version_id,
                    acquisition_id,
                    document_version_id,
                    chunk_set_id,
                    chunk_set_content_hash,
                    embedding_model_id,
                    embedding_configuration_hash,
                    draft.index_bundle.dense_cardinality,
                    draft.index_bundle.lexical_cardinality,
                    draft.index_bundle.exact_identifier_cardinality,
                    dense_content_hash,
                    lexical_content_hash,
                    exact_content_hash,
                    dense_artifact_id,
                    lexical_artifact_id,
                    recorded_at,
                ),
            )
            for row in dense_rows:
                connection.execute(
                    """
                    INSERT INTO atlas_ingestion.dense_chunk_embeddings (
                        tenant_id, workspace_id, index_version_id, chunk_id,
                        chunk_text_hash, embedding, ordinal
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s::vector, %s
                    )
                    """,
                    (
                        command.tenant_id,
                        command.workspace_id,
                        index_version_id,
                        row["chunk_id"],
                        row["chunk_text_hash"],
                        row["embedding"],
                        row["ordinal"],
                    ),
                )
            for row in lexical_rows:
                connection.execute(
                    """
                    INSERT INTO atlas_ingestion.lexical_chunk_documents (
                        tenant_id, workspace_id, index_version_id, chunk_id,
                        chunk_text_hash, body, tsv, ordinal
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, to_tsvector('english', %s), %s
                    )
                    """,
                    (
                        command.tenant_id,
                        command.workspace_id,
                        index_version_id,
                        row["chunk_id"],
                        row["chunk_text_hash"],
                        row["body"],
                        row["body"],
                        row["ordinal"],
                    ),
                )
            for row in exact_rows:
                connection.execute(
                    """
                    INSERT INTO atlas_ingestion.exact_identifier_hits (
                        tenant_id, workspace_id, index_version_id, chunk_id,
                        identifier_kind, identifier_value, ordinal
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        command.tenant_id,
                        command.workspace_id,
                        index_version_id,
                        row["chunk_id"],
                        row["identifier_kind"],
                        row["identifier_value"],
                        row["ordinal"],
                    ),
                )
            connection.execute(
                """
                INSERT INTO atlas_ingestion.retrieval_publication_manifests (
                    tenant_id, workspace_id, publication_id, manifest_id,
                    index_version_id, acquisition_id, document_version_id, chunk_set_id,
                    lifecycle, searchable, manifest, recorded_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    draft.publication_id,
                    draft.manifest_id,
                    index_version_id,
                    draft.acquisition_id,
                    draft.document_version_id,
                    draft.chunk_set_id,
                    draft.lifecycle.value,
                    draft.searchable,
                    Jsonb(draft.model_dump(mode="json")),
                    recorded_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO atlas_ingestion.retrieval_lifecycle_events (
                    tenant_id, workspace_id, event_id, acquisition_id,
                    index_version_id, event_type, payload, recorded_at
                ) VALUES (
                    %s, %s, %s, %s, %s, 'IndexVersionStaged', %s, %s
                )
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    uuid4(),
                    acquisition_id,
                    index_version_id,
                    Jsonb(
                        {
                            "index_version_id": str(index_version_id),
                            "publication_id": draft.publication_id,
                            "chunk_set_id": chunk_set_id,
                            "searchable": False,
                        }
                    ),
                    recorded_at,
                ),
            )
            connection.commit()
        return index_version_id

    def get_retrieval_index_version(
        self,
        *,
        context: ArtifactCommandContext,
        index_version_id: UUID,
    ) -> dict[str, Any] | None:
        command = ArtifactCommandContext.model_validate(context)
        row = self._database.fetch_one(
            """
            SELECT index_version_id, status, dense_cardinality, lexical_cardinality,
                   exact_identifier_cardinality, document_version_id, chunk_set_id,
                   acquisition_id
            FROM atlas_ingestion.retrieval_index_versions
            WHERE tenant_id = %s AND workspace_id = %s AND index_version_id = %s
            """,
            (command.tenant_id, command.workspace_id, index_version_id),
        )
        if row is None:
            return None
        published = self._database.fetch_one(
            """
            SELECT publication_id
            FROM atlas_ingestion.retrieval_publication_manifests
            WHERE tenant_id = %s AND workspace_id = %s AND index_version_id = %s
              AND lifecycle = 'published'
            """,
            (command.tenant_id, command.workspace_id, index_version_id),
        )
        validated = self._database.fetch_one(
            """
            SELECT publication_id
            FROM atlas_ingestion.retrieval_publication_manifests
            WHERE tenant_id = %s AND workspace_id = %s AND index_version_id = %s
              AND lifecycle = 'index_validated'
            """,
            (command.tenant_id, command.workspace_id, index_version_id),
        )
        publication_id = (
            published[0]
            if published is not None
            else (validated[0] if validated is not None else None)
        )
        return {
            "index_version_id": row[0],
            "status": row[1],
            "dense_cardinality": row[2],
            "lexical_cardinality": row[3],
            "exact_identifier_cardinality": row[4],
            "document_version_id": row[5],
            "chunk_set_id": row[6],
            "acquisition_id": row[7],
            "publication_id": publication_id,
        }

    def get_retrieval_publication_manifest(
        self,
        *,
        context: ArtifactCommandContext,
        index_version_id: UUID,
        lifecycle: object,
    ) -> dict[str, Any] | None:
        command = ArtifactCommandContext.model_validate(context)
        lifecycle_value = getattr(lifecycle, "value", lifecycle)
        row = self._database.fetch_one(
            """
            SELECT manifest
            FROM atlas_ingestion.retrieval_publication_manifests
            WHERE tenant_id = %s AND workspace_id = %s
              AND index_version_id = %s AND lifecycle = %s
            """,
            (command.tenant_id, command.workspace_id, index_version_id, lifecycle_value),
        )
        if row is None:
            return None
        return dict(row[0])

    def count_dense_rows(self, *, context: ArtifactCommandContext, index_version_id: UUID) -> int:
        command = ArtifactCommandContext.model_validate(context)
        row = self._database.fetch_one(
            """
            SELECT count(*)::int
            FROM atlas_ingestion.dense_chunk_embeddings
            WHERE tenant_id = %s AND workspace_id = %s AND index_version_id = %s
            """,
            (command.tenant_id, command.workspace_id, index_version_id),
        )
        return int(row[0]) if row is not None else 0

    def count_lexical_rows(self, *, context: ArtifactCommandContext, index_version_id: UUID) -> int:
        command = ArtifactCommandContext.model_validate(context)
        row = self._database.fetch_one(
            """
            SELECT count(*)::int
            FROM atlas_ingestion.lexical_chunk_documents
            WHERE tenant_id = %s AND workspace_id = %s AND index_version_id = %s
            """,
            (command.tenant_id, command.workspace_id, index_version_id),
        )
        return int(row[0]) if row is not None else 0

    def activate_retrieval_publication(
        self,
        *,
        context: ArtifactCommandContext,
        index_version_id: UUID,
        manifest: RetrievalPublicationManifestDraft,
        recorded_at: datetime,
    ) -> None:
        command = ArtifactCommandContext.model_validate(context)
        draft = RetrievalPublicationManifestDraft.model_validate(manifest)
        with self._database.connect() as connection:
            current = connection.execute(
                """
                SELECT status FROM atlas_ingestion.retrieval_index_versions
                WHERE tenant_id = %s AND workspace_id = %s AND index_version_id = %s
                FOR UPDATE
                """,
                (command.tenant_id, command.workspace_id, index_version_id),
            ).fetchone()
            if current is None:
                raise DocumentProcessingIntegrityError("index version missing")
            if current[0] == "active":
                return
            if current[0] != "staging":
                raise DocumentProcessingConflictError(
                    f"cannot activate index version in status {current[0]}"
                )

            prior = connection.execute(
                """
                SELECT index_version_id
                FROM atlas_ingestion.document_retrieval_active
                WHERE tenant_id = %s AND workspace_id = %s
                  AND document_version_id = %s AND chunk_set_id = %s
                FOR UPDATE
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    draft.document_version_id,
                    draft.chunk_set_id,
                ),
            ).fetchone()
            if prior is not None and prior[0] != index_version_id:
                connection.execute(
                    """
                    UPDATE atlas_ingestion.retrieval_index_versions
                    SET status = 'superseded'
                    WHERE tenant_id = %s AND workspace_id = %s AND index_version_id = %s
                    """,
                    (command.tenant_id, command.workspace_id, prior[0]),
                )
                connection.execute(
                    """
                    INSERT INTO atlas_ingestion.retrieval_lifecycle_events (
                        tenant_id, workspace_id, event_id, acquisition_id,
                        index_version_id, event_type, payload, recorded_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, 'DocumentSuperseded', %s, %s
                    )
                    """,
                    (
                        command.tenant_id,
                        command.workspace_id,
                        uuid4(),
                        draft.acquisition_id,
                        prior[0],
                        Jsonb(
                            {
                                "superseded_by": str(index_version_id),
                                "publication_id": draft.publication_id,
                            }
                        ),
                        recorded_at,
                    ),
                )

            connection.execute(
                """
                UPDATE atlas_ingestion.retrieval_index_versions
                SET status = 'active'
                WHERE tenant_id = %s AND workspace_id = %s AND index_version_id = %s
                """,
                (command.tenant_id, command.workspace_id, index_version_id),
            )
            connection.execute(
                """
                INSERT INTO atlas_ingestion.retrieval_publication_manifests (
                    tenant_id, workspace_id, publication_id, manifest_id,
                    index_version_id, acquisition_id, document_version_id, chunk_set_id,
                    lifecycle, searchable, manifest, recorded_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (tenant_id, workspace_id, index_version_id, lifecycle) DO NOTHING
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    draft.publication_id,
                    draft.manifest_id,
                    index_version_id,
                    draft.acquisition_id,
                    draft.document_version_id,
                    draft.chunk_set_id,
                    draft.lifecycle.value,
                    draft.searchable,
                    Jsonb(draft.model_dump(mode="json")),
                    recorded_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO atlas_ingestion.document_retrieval_active (
                    tenant_id, workspace_id, document_version_id, chunk_set_id,
                    index_version_id, publication_id, activated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (tenant_id, workspace_id, document_version_id, chunk_set_id)
                DO UPDATE SET
                    index_version_id = EXCLUDED.index_version_id,
                    publication_id = EXCLUDED.publication_id,
                    activated_at = EXCLUDED.activated_at
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    draft.document_version_id,
                    draft.chunk_set_id,
                    index_version_id,
                    draft.publication_id,
                    recorded_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO atlas_ingestion.retrieval_lifecycle_events (
                    tenant_id, workspace_id, event_id, acquisition_id,
                    index_version_id, event_type, payload, recorded_at
                ) VALUES (
                    %s, %s, %s, %s, %s, 'DocumentPublished', %s, %s
                )
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    uuid4(),
                    draft.acquisition_id,
                    index_version_id,
                    Jsonb(
                        {
                            "index_version_id": str(index_version_id),
                            "publication_id": draft.publication_id,
                            "searchable": True,
                        }
                    ),
                    recorded_at,
                ),
            )
            connection.commit()

    def search_lexical_active(
        self,
        *,
        context: ArtifactCommandContext,
        document_version_id: str,
        chunk_set_id: str,
        query: str,
    ) -> list[str]:
        command = ArtifactCommandContext.model_validate(context)
        with self._database.connect(autocommit=True) as connection:
            rows = connection.execute(
                """
                SELECT lcd.chunk_id
                FROM atlas_ingestion.document_retrieval_active dra
                JOIN atlas_ingestion.lexical_chunk_documents lcd
                  ON lcd.tenant_id = dra.tenant_id
                 AND lcd.workspace_id = dra.workspace_id
                 AND lcd.index_version_id = dra.index_version_id
                WHERE dra.tenant_id = %s
                  AND dra.workspace_id = %s
                  AND dra.document_version_id = %s
                  AND dra.chunk_set_id = %s
                  AND lcd.tsv @@ plainto_tsquery('english', %s)
                ORDER BY lcd.ordinal ASC
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    document_version_id,
                    chunk_set_id,
                    query,
                ),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def search_lexical_any_status(
        self,
        *,
        context: ArtifactCommandContext,
        index_version_id: UUID,
        query: str,
    ) -> list[str]:
        """Test helper: search a specific version including staging (not production API)."""
        command = ArtifactCommandContext.model_validate(context)
        with self._database.connect(autocommit=True) as connection:
            rows = connection.execute(
                """
                SELECT chunk_id
                FROM atlas_ingestion.lexical_chunk_documents
                WHERE tenant_id = %s
                  AND workspace_id = %s
                  AND index_version_id = %s
                  AND tsv @@ plainto_tsquery('english', %s)
                ORDER BY ordinal ASC
                """,
                (command.tenant_id, command.workspace_id, index_version_id, query),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def rollback_retrieval_publication(
        self,
        *,
        context: ArtifactCommandContext,
        document_version_id: str,
        chunk_set_id: str,
        recorded_at: datetime,
    ) -> bool:
        del recorded_at
        command = ArtifactCommandContext.model_validate(context)
        with self._database.connect() as connection:
            active = connection.execute(
                """
                SELECT index_version_id
                FROM atlas_ingestion.document_retrieval_active
                WHERE tenant_id = %s AND workspace_id = %s
                  AND document_version_id = %s AND chunk_set_id = %s
                FOR UPDATE
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    document_version_id,
                    chunk_set_id,
                ),
            ).fetchone()
            if active is None:
                connection.commit()
                return False
            connection.execute(
                """
                UPDATE atlas_ingestion.retrieval_index_versions
                SET status = 'superseded'
                WHERE tenant_id = %s AND workspace_id = %s AND index_version_id = %s
                """,
                (command.tenant_id, command.workspace_id, active[0]),
            )
            connection.execute(
                """
                DELETE FROM atlas_ingestion.document_retrieval_active
                WHERE tenant_id = %s AND workspace_id = %s
                  AND document_version_id = %s AND chunk_set_id = %s
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    document_version_id,
                    chunk_set_id,
                ),
            )
            connection.commit()
            return True


def _row_to_attempt(row: Row) -> DocumentParserAttempt:
    return DocumentParserAttempt(
        attempt_id=row[0],
        acquisition_id=row[1],
        artifact_id=row[2],
        operation=AttemptOperation(row[3]),
        configuration_hash=row[4],
        input_binding_hash=row[5],
        actor_id=row[6],
        trace_id=row[7],
        created_at=row[8],
    )
