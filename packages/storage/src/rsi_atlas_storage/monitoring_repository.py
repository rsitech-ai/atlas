"""Persist monitoring alerts, lifecycle events, and research invalidations."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb
from rsi_atlas_contracts import (
    Alert,
    AlertEvent,
    ArtifactCommandContext,
    ResearchInvalidation,
)

from rsi_atlas_storage.database import PostgresDatabase


class MonitoringRepository:
    """Append-oriented persistence for Phase 5 monitoring artifacts."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def save_alert(self, *, alert: Alert) -> None:
        command = ArtifactCommandContext.model_validate(alert.context)
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO atlas_monitoring.alerts (
                    tenant_id, workspace_id, alert_id, dedup_key, rule_id, subject_id,
                    severity, status, detected_at, event_time, current_observation_id,
                    current_envelope_id, payload, recorded_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (tenant_id, workspace_id, alert_id) DO NOTHING
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    alert.alert_id,
                    alert.dedup_key,
                    alert.rule_id,
                    alert.subject_id,
                    alert.severity.value,
                    alert.status.value,
                    alert.detected_at,
                    alert.event_time,
                    alert.current_observation_id,
                    alert.current_envelope_id,
                    Jsonb(alert.model_dump(mode="json")),
                    alert.detected_at,
                ),
            )
            connection.commit()

    def get_alert_by_dedup(
        self, *, context: ArtifactCommandContext, dedup_key: str
    ) -> dict[str, Any] | None:
        command = ArtifactCommandContext.model_validate(context)
        row = self._database.fetch_one(
            """
            SELECT payload
            FROM atlas_monitoring.alerts
            WHERE tenant_id = %s AND workspace_id = %s AND dedup_key = %s
            """,
            (command.tenant_id, command.workspace_id, dedup_key),
        )
        if row is None:
            return None
        return dict(row[0])

    def get_alert(self, *, context: ArtifactCommandContext, alert_id: str) -> dict[str, Any] | None:
        command = ArtifactCommandContext.model_validate(context)
        row = self._database.fetch_one(
            """
            SELECT payload
            FROM atlas_monitoring.alerts
            WHERE tenant_id = %s AND workspace_id = %s AND alert_id = %s
            """,
            (command.tenant_id, command.workspace_id, alert_id),
        )
        if row is None:
            return None
        return dict(row[0])

    def update_alert_status(self, *, alert: Alert) -> None:
        command = ArtifactCommandContext.model_validate(alert.context)
        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE atlas_monitoring.alerts
                SET status = %s, payload = %s
                WHERE tenant_id = %s AND workspace_id = %s AND alert_id = %s
                """,
                (
                    alert.status.value,
                    Jsonb(alert.model_dump(mode="json")),
                    command.tenant_id,
                    command.workspace_id,
                    alert.alert_id,
                ),
            )
            connection.commit()

    def save_alert_event(self, *, event: AlertEvent) -> None:
        command = ArtifactCommandContext.model_validate(event.context)
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO atlas_monitoring.alert_events (
                    tenant_id, workspace_id, event_id, alert_id, from_status, to_status,
                    note, recorded_at, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, workspace_id, event_id) DO NOTHING
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    event.event_id,
                    event.alert_id,
                    None if event.from_status is None else event.from_status.value,
                    event.to_status.value,
                    event.note,
                    event.recorded_at,
                    Jsonb(event.model_dump(mode="json")),
                ),
            )
            connection.commit()

    def list_alert_events(
        self, *, context: ArtifactCommandContext, alert_id: str
    ) -> list[dict[str, Any]]:
        command = ArtifactCommandContext.model_validate(context)
        query = """
            SELECT payload
            FROM atlas_monitoring.alert_events
            WHERE tenant_id = %s AND workspace_id = %s AND alert_id = %s
            ORDER BY recorded_at ASC
            """
        parameters = (command.tenant_id, command.workspace_id, alert_id)
        with self._database.connect(autocommit=True) as connection, connection.cursor() as cursor:
            cursor.execute(query, parameters)
            rows = cursor.fetchall()
        return [dict(row[0]) for row in rows]

    def save_invalidation(self, *, invalidation: ResearchInvalidation) -> None:
        command = ArtifactCommandContext.model_validate(invalidation.context)
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO atlas_monitoring.research_invalidations (
                    tenant_id, workspace_id, invalidation_id, reason, subject_id,
                    observation_id, envelope_id, alert_id, payload, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, workspace_id, invalidation_id) DO NOTHING
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    invalidation.invalidation_id,
                    invalidation.reason.value,
                    invalidation.subject_id,
                    invalidation.observation_id,
                    invalidation.envelope_id,
                    invalidation.alert_id,
                    Jsonb(invalidation.model_dump(mode="json")),
                    invalidation.recorded_at,
                ),
            )
            connection.commit()

    def list_invalidations(
        self, *, context: ArtifactCommandContext, subject_id: str | None = None
    ) -> list[dict[str, Any]]:
        command = ArtifactCommandContext.model_validate(context)
        if subject_id is None:
            query = """
                SELECT payload
                FROM atlas_monitoring.research_invalidations
                WHERE tenant_id = %s AND workspace_id = %s
                ORDER BY recorded_at DESC
                """
            parameters: tuple[object, ...] = (command.tenant_id, command.workspace_id)
        else:
            query = """
                SELECT payload
                FROM atlas_monitoring.research_invalidations
                WHERE tenant_id = %s AND workspace_id = %s AND subject_id = %s
                ORDER BY recorded_at DESC
                """
            parameters = (command.tenant_id, command.workspace_id, subject_id)
        with self._database.connect(autocommit=True) as connection, connection.cursor() as cursor:
            cursor.execute(query, parameters)
            rows = cursor.fetchall()
        return [dict(row[0]) for row in rows]
