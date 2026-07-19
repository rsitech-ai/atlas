"""Persist raw envelopes, bitemporal observations, and quarantine records."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb
from rsi_atlas_contracts import (
    ArtifactCommandContext,
    Observation,
    QuarantineRecord,
    RawEnvelope,
)

from rsi_atlas_storage.database import PostgresDatabase


class ObservationRepository:
    """Append-oriented persistence for Phase 4 structured observations."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def save_envelope(self, *, envelope: RawEnvelope, payload: dict[str, Any]) -> None:
        command = ArtifactCommandContext.model_validate(envelope.context)
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO atlas_observations.raw_envelopes (
                    tenant_id, workspace_id, envelope_id, collector_id, provider,
                    source_family, payload_sha256, payload_artifact_id, payload, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, workspace_id, envelope_id) DO NOTHING
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    envelope.envelope_id,
                    envelope.collector_id,
                    envelope.provider,
                    envelope.source_family.value,
                    envelope.payload_sha256,
                    envelope.payload_artifact_id,
                    Jsonb(payload),
                    envelope.received_at,
                ),
            )
            connection.commit()

    def save_observation(self, *, observation: Observation) -> None:
        command = ArtifactCommandContext.model_validate(observation.context)
        header = observation.header
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO atlas_observations.observations (
                    tenant_id, workspace_id, observation_id, envelope_id, source_family,
                    observation_type, subject_ids, event_time, available_time, valid_time,
                    system_time, quality, provider_quality, payload, recorded_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (tenant_id, workspace_id, observation_id) DO NOTHING
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    header.observation_id,
                    header.envelope_id,
                    header.source_family.value,
                    header.observation_type.value,
                    list(header.subject_ids),
                    header.event_time,
                    header.available_time,
                    header.valid_time,
                    header.system_time,
                    header.quality.value,
                    header.provider_quality.value,
                    Jsonb(observation.model_dump(mode="json")),
                    header.system_time,
                ),
            )
            connection.commit()

    def save_quarantine(self, *, quarantine: QuarantineRecord) -> None:
        command = ArtifactCommandContext.model_validate(quarantine.context)
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO atlas_observations.quarantine (
                    tenant_id, workspace_id, quarantine_id, envelope_id, observation_id,
                    reasons, severity, payload, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, workspace_id, quarantine_id) DO NOTHING
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    quarantine.quarantine_id,
                    quarantine.envelope_id,
                    quarantine.observation_id,
                    list(quarantine.reasons),
                    quarantine.severity,
                    Jsonb(quarantine.model_dump(mode="json")),
                    quarantine.recorded_at,
                ),
            )
            connection.commit()

    def get_observation(
        self, *, context: ArtifactCommandContext, observation_id: str
    ) -> dict[str, Any] | None:
        command = ArtifactCommandContext.model_validate(context)
        row = self._database.fetch_one(
            """
            SELECT payload
            FROM atlas_observations.observations
            WHERE tenant_id = %s AND workspace_id = %s AND observation_id = %s
            """,
            (command.tenant_id, command.workspace_id, observation_id),
        )
        if row is None:
            return None
        return dict(row[0])

    def list_as_of(
        self,
        *,
        context: ArtifactCommandContext,
        as_of: datetime,
        subject_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Point-in-time read: available_time <= as_of (leakage-safe eligibility)."""
        command = ArtifactCommandContext.model_validate(context)
        if subject_id is None:
            query = """
                SELECT payload
                FROM atlas_observations.observations
                WHERE tenant_id = %s
                  AND workspace_id = %s
                  AND available_time <= %s
                ORDER BY available_time ASC, observation_id ASC
                """
            parameters: tuple[object, ...] = (
                command.tenant_id,
                command.workspace_id,
                as_of,
            )
        else:
            query = """
                SELECT payload
                FROM atlas_observations.observations
                WHERE tenant_id = %s
                  AND workspace_id = %s
                  AND available_time <= %s
                  AND %s = ANY(subject_ids)
                ORDER BY available_time ASC, observation_id ASC
                """
            parameters = (command.tenant_id, command.workspace_id, as_of, subject_id)
        with self._database.connect(autocommit=True) as connection, connection.cursor() as cursor:
            cursor.execute(query, parameters)
            rows = cursor.fetchall()
        return [dict(row[0]) for row in rows]

    def update_observation_quality(self, *, observation: Observation) -> None:
        """Replace payload for orphan/reorg updates while preserving primary key."""
        command = ArtifactCommandContext.model_validate(observation.context)
        header = observation.header
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE atlas_observations.observations
                SET quality = %s,
                    payload = %s,
                    system_time = %s
                WHERE tenant_id = %s
                  AND workspace_id = %s
                  AND observation_id = %s
                """,
                (
                    header.quality.value,
                    Jsonb(observation.model_dump(mode="json")),
                    header.system_time,
                    command.tenant_id,
                    command.workspace_id,
                    header.observation_id,
                ),
            )
            connection.commit()
