import hashlib
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb
from rsi_atlas_contracts import (
    AdmissionOutcome,
    ArtifactCommandContext,
    ArtifactID,
    DocumentAdmissionRecord,
    DocumentLifecycle,
)

from rsi_atlas_storage.database import PostgresDatabase, Row


class AcquisitionConflictError(RuntimeError):
    """Raised when one acquisition identity is reused for different immutable evidence."""


class AcquisitionRepository:
    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def find(
        self,
        *,
        context: ArtifactCommandContext,
        acquisition_id: UUID,
    ) -> DocumentAdmissionRecord | None:
        command_context = ArtifactCommandContext.model_validate(context)
        if not isinstance(acquisition_id, UUID):
            raise TypeError("acquisition identity must be a UUID")
        with self._database.connect(autocommit=True) as connection:
            return self._find_with_connection(
                connection,
                context=command_context,
                acquisition_id=acquisition_id,
            )

    def find_duplicate(
        self,
        *,
        context: ArtifactCommandContext,
        artifact_id: ArtifactID,
    ) -> UUID | None:
        command_context = ArtifactCommandContext.model_validate(context)
        identifier = _require_artifact_id(artifact_id)
        with self._database.connect(autocommit=True) as connection:
            return self._find_primary_acquisition(
                connection,
                context=command_context,
                artifact_id=identifier,
            )

    def record(self, record: DocumentAdmissionRecord) -> DocumentAdmissionRecord:
        requested = DocumentAdmissionRecord.model_validate(record)
        context = requested.context
        with self._database.connect() as connection:
            self._lock_command_and_artifact(connection, requested)
            existing = self._find_with_connection(
                connection,
                context=context,
                acquisition_id=requested.request.acquisition_id,
            )
            if existing is not None:
                if _same_immutable_command(existing, requested):
                    return existing
                raise AcquisitionConflictError(
                    "acquisition identity already names different evidence"
                )

            primary_id = self._find_primary_acquisition(
                connection,
                context=context,
                artifact_id=requested.artifact.artifact_id,
            )
            resolved = self._resolve_duplicate(requested, primary_id=primary_id)
            self._insert(connection, resolved)
            stored = self._find_with_connection(
                connection,
                context=context,
                acquisition_id=resolved.request.acquisition_id,
            )
            if stored != resolved:
                raise RuntimeError("stored document admission differs from validated evidence")
            return stored

    @staticmethod
    def _lock_command_and_artifact(
        connection: Connection[Row], record: DocumentAdmissionRecord
    ) -> None:
        command_key = _advisory_lock_key(
            f"command:{record.context.tenant_id}:{record.context.workspace_id}:"
            f"{record.request.acquisition_id}"
        )
        artifact_key = _advisory_lock_key(
            f"artifact:{record.context.tenant_id}:{record.context.workspace_id}:"
            f"{record.artifact.artifact_id}"
        )
        for key in sorted((command_key, artifact_key)):
            connection.execute("SELECT pg_advisory_xact_lock(%s)", (key,))

    @staticmethod
    def _resolve_duplicate(
        record: DocumentAdmissionRecord,
        *,
        primary_id: UUID | None,
    ) -> DocumentAdmissionRecord:
        if primary_id is None:
            if record.outcome is AdmissionOutcome.MARK_EXACT_DUPLICATE:
                raise AcquisitionConflictError("exact duplicate target does not exist")
            return record
        if (
            record.outcome is AdmissionOutcome.MARK_EXACT_DUPLICATE
            and record.duplicate_of_acquisition_id != primary_id
        ):
            raise AcquisitionConflictError("exact duplicate target differs from durable evidence")
        return DocumentAdmissionRecord.model_validate(
            record.model_copy(
                update={
                    "lifecycle": DocumentLifecycle.DUPLICATE,
                    "outcome": AdmissionOutcome.MARK_EXACT_DUPLICATE,
                    "reason_codes": ("exact_duplicate",),
                    "duplicate_of_acquisition_id": primary_id,
                }
            )
        )

    @staticmethod
    def _insert(connection: Connection[Row], record: DocumentAdmissionRecord) -> None:
        context = record.context
        acquisition_id = record.request.acquisition_id
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
                acquisition_id,
                str(record.artifact.artifact_id),
                context.actor_id,
                context.trace_id,
                Jsonb(record.request.model_dump(mode="json")),
                Jsonb(record.profile.model_dump(mode="json")),
                record.recorded_at,
            ),
        )
        record_payload = record.model_dump(mode="json")
        connection.execute(
            """
            INSERT INTO atlas_ingestion.document_admission_decisions (
                tenant_id, workspace_id, acquisition_id, lifecycle, outcome, reason_codes,
                duplicate_of_acquisition_id, record, recorded_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                context.tenant_id,
                context.workspace_id,
                acquisition_id,
                record.lifecycle.value,
                record.outcome.value,
                Jsonb(list(record.reason_codes)),
                record.duplicate_of_acquisition_id,
                Jsonb(record_payload),
                record.recorded_at,
            ),
        )
        if record.duplicate_of_acquisition_id is not None:
            connection.execute(
                """
                INSERT INTO atlas_ingestion.document_duplicate_links (
                    tenant_id, workspace_id, acquisition_id,
                    duplicate_of_acquisition_id, recorded_at
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    context.tenant_id,
                    context.workspace_id,
                    acquisition_id,
                    record.duplicate_of_acquisition_id,
                    record.recorded_at,
                ),
            )
        connection.execute(
            """
            INSERT INTO atlas_ingestion.outbox_events (
                tenant_id, workspace_id, event_id, acquisition_id,
                event_type, payload, recorded_at
            ) VALUES (%s, %s, %s, %s, 'DocumentAdmissionRecorded', %s, %s)
            """,
            (
                context.tenant_id,
                context.workspace_id,
                acquisition_id,
                acquisition_id,
                Jsonb(record_payload),
                record.recorded_at,
            ),
        )

    @staticmethod
    def _find_with_connection(
        connection: Connection[Row],
        *,
        context: ArtifactCommandContext,
        acquisition_id: UUID,
    ) -> DocumentAdmissionRecord | None:
        row = connection.execute(
            """
            SELECT d.record
            FROM atlas_ingestion.document_admission_decisions AS d
            WHERE d.tenant_id = %s AND d.workspace_id = %s AND d.acquisition_id = %s
            """,
            (context.tenant_id, context.workspace_id, acquisition_id),
        ).fetchone()
        if row is None:
            return None
        return DocumentAdmissionRecord.model_validate(row[0])

    @staticmethod
    def _find_primary_acquisition(
        connection: Connection[Row],
        *,
        context: ArtifactCommandContext,
        artifact_id: ArtifactID,
    ) -> UUID | None:
        row = connection.execute(
            """
            SELECT a.acquisition_id
            FROM atlas_ingestion.document_acquisitions AS a
            JOIN atlas_ingestion.document_admission_decisions AS d
              USING (tenant_id, workspace_id, acquisition_id)
            WHERE a.tenant_id = %s AND a.workspace_id = %s AND a.artifact_id = %s
              AND d.outcome <> 'mark_exact_duplicate'
            ORDER BY a.recorded_at, a.acquisition_id
            LIMIT 1
            """,
            (context.tenant_id, context.workspace_id, str(artifact_id)),
        ).fetchone()
        return None if row is None else row[0]


def _same_immutable_command(
    existing: DocumentAdmissionRecord,
    requested: DocumentAdmissionRecord,
) -> bool:
    return (
        existing.context == requested.context
        and existing.request == requested.request
        and existing.artifact == requested.artifact
    )


def _advisory_lock_key(value: str) -> int:
    unsigned = int.from_bytes(hashlib.sha256(value.encode("utf-8")).digest()[:8], "big")
    return unsigned if unsigned < 2**63 else unsigned - 2**64


def _require_artifact_id(value: ArtifactID) -> ArtifactID:
    rendered = str(value)
    if (
        not rendered.startswith("sha256:")
        or len(rendered) != 71
        or any(character not in "0123456789abcdef" for character in rendered[7:])
    ):
        raise ValueError("artifact identifier must be a sha256 lowercase hexadecimal digest")
    return ArtifactID(rendered)
