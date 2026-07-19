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
from rsi_atlas_contracts import ArtifactCommandContext
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
