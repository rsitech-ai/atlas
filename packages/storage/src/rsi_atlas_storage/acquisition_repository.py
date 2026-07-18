import hashlib
from datetime import UTC, datetime
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb
from rsi_atlas_contracts import (
    AcquisitionRequest,
    AdmissionOutcome,
    ArtifactCommandContext,
    ArtifactDescriptor,
    ArtifactID,
    DocumentAdmissionRecord,
    DocumentLifecycle,
    PDFSafetyProfile,
)

from rsi_atlas_storage.database import PostgresDatabase, Row


class AcquisitionConflictError(RuntimeError):
    """Raised when one acquisition identity is reused for different immutable evidence."""


class AcquisitionIntegrityError(RuntimeError):
    """Raised when duplicated durable admission representations no longer agree."""


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
            SELECT
                a.artifact_id,
                c.digest,
                c.schema_version,
                c.algorithm,
                c.size_bytes,
                c.media_type,
                a.actor_id,
                a.trace_id,
                a.request,
                a.profile,
                a.recorded_at,
                d.lifecycle,
                d.outcome,
                d.reason_codes,
                d.duplicate_of_acquisition_id,
                d.record,
                d.recorded_at,
                l.duplicate_of_acquisition_id,
                l.recorded_at,
                o.payload,
                o.event_id,
                o.event_type,
                o.recorded_at
            FROM atlas_ingestion.document_acquisitions AS a
            JOIN atlas_ingestion.document_admission_decisions AS d
              USING (tenant_id, workspace_id, acquisition_id)
            JOIN atlas_core.artifact_contents AS c USING (artifact_id)
            LEFT JOIN atlas_ingestion.document_duplicate_links AS l
              USING (tenant_id, workspace_id, acquisition_id)
            JOIN atlas_ingestion.outbox_events AS o
              USING (tenant_id, workspace_id, acquisition_id)
            WHERE a.tenant_id = %s AND a.workspace_id = %s AND a.acquisition_id = %s
            """,
            (context.tenant_id, context.workspace_id, acquisition_id),
        ).fetchone()
        if row is None:
            return None
        try:
            request = AcquisitionRequest.model_validate(row[8])
            profile = PDFSafetyProfile.model_validate(row[9])
            artifact = ArtifactDescriptor(
                artifact_id=ArtifactID(row[0]),
                digest=row[1],
                schema_version=row[2],
                algorithm=row[3],
                size_bytes=row[4],
                media_type=row[5],
            )
            reconstructed = DocumentAdmissionRecord(
                context=ArtifactCommandContext(
                    tenant_id=context.tenant_id,
                    workspace_id=context.workspace_id,
                    actor_id=row[6],
                    trace_id=row[7],
                ),
                request=request,
                artifact=artifact,
                profile=profile,
                lifecycle=row[11],
                outcome=row[12],
                reason_codes=tuple(row[13]),
                duplicate_of_acquisition_id=row[14],
                recorded_at=_as_utc(row[16]),
            )
            record_snapshot = DocumentAdmissionRecord.model_validate(row[15])
            outbox_snapshot = DocumentAdmissionRecord.model_validate(row[19])
        except Exception as error:
            raise AcquisitionIntegrityError("document admission evidence is invalid") from error
        timestamps = tuple(
            None if value is None else _as_utc(value)
            for value in (row[10], row[16], row[18], row[22])
        )
        if request.acquisition_id != acquisition_id:
            raise AcquisitionIntegrityError("document acquisition identity differs")
        if reconstructed != record_snapshot or reconstructed != outbox_snapshot:
            raise AcquisitionIntegrityError("document admission representations differ")
        if reconstructed.duplicate_of_acquisition_id != row[17]:
            raise AcquisitionIntegrityError("document duplicate-link representation differs")
        if any(value is not None and value != reconstructed.recorded_at for value in timestamps):
            raise AcquisitionIntegrityError("document admission timestamps differ")
        if row[20] != acquisition_id or row[21] != "DocumentAdmissionRecorded":
            raise AcquisitionIntegrityError("document outbox identity differs")
        return reconstructed

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


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise AcquisitionIntegrityError("document admission timestamp is invalid")
    return value.astimezone(UTC)
