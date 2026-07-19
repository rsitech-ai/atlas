"""Postgres-durable research workflow checkpoint + artifact rehydration."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb
from rsi_atlas_contracts import ArtifactCommandContext

from rsi_atlas_storage.database import PostgresDatabase


class WorkflowRepository:
    """Upsert checkpoints and intermediate payloads for interrupt/resume."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def save_attempt(
        self,
        *,
        context: ArtifactCommandContext,
        workflow_id: UUID,
        query_id: UUID,
        step: str,
        updated_at: Any,
        checkpoint: dict[str, Any],
        title: str = "",
        detail: str = "",
        run_id: str | None = None,
        packet_id: str | None = None,
        finding_task_id: str | None = None,
        report_id: str | None = None,
        query_payload: dict[str, Any] | None = None,
        packet_payload: dict[str, Any] | None = None,
        finding_payload: dict[str, Any] | None = None,
        report_payload: dict[str, Any] | None = None,
    ) -> None:
        command = ArtifactCommandContext.model_validate(context)
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO atlas_research.research_workflow_attempts (
                    tenant_id, workspace_id, workflow_id, query_id, step,
                    run_id, packet_id, finding_task_id, report_id, detail, title,
                    checkpoint, query_payload, packet_payload, finding_payload,
                    report_payload, updated_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (tenant_id, workspace_id, workflow_id) DO UPDATE SET
                    query_id = EXCLUDED.query_id,
                    step = EXCLUDED.step,
                    run_id = EXCLUDED.run_id,
                    packet_id = EXCLUDED.packet_id,
                    finding_task_id = EXCLUDED.finding_task_id,
                    report_id = EXCLUDED.report_id,
                    detail = EXCLUDED.detail,
                    title = EXCLUDED.title,
                    checkpoint = EXCLUDED.checkpoint,
                    query_payload = COALESCE(
                        EXCLUDED.query_payload,
                        atlas_research.research_workflow_attempts.query_payload
                    ),
                    packet_payload = COALESCE(
                        EXCLUDED.packet_payload,
                        atlas_research.research_workflow_attempts.packet_payload
                    ),
                    finding_payload = COALESCE(
                        EXCLUDED.finding_payload,
                        atlas_research.research_workflow_attempts.finding_payload
                    ),
                    report_payload = COALESCE(
                        EXCLUDED.report_payload,
                        atlas_research.research_workflow_attempts.report_payload
                    ),
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    workflow_id,
                    query_id,
                    step,
                    run_id,
                    packet_id,
                    finding_task_id,
                    report_id,
                    detail,
                    title,
                    Jsonb(checkpoint),
                    Jsonb(query_payload) if query_payload is not None else None,
                    Jsonb(packet_payload) if packet_payload is not None else None,
                    Jsonb(finding_payload) if finding_payload is not None else None,
                    Jsonb(report_payload) if report_payload is not None else None,
                    updated_at,
                ),
            )
            connection.commit()

    def get_attempt(
        self, *, context: ArtifactCommandContext, workflow_id: UUID
    ) -> dict[str, Any] | None:
        command = ArtifactCommandContext.model_validate(context)
        row = self._database.fetch_one(
            """
            SELECT workflow_id, query_id, step, run_id, packet_id, finding_task_id,
                   report_id, detail, title, checkpoint, query_payload, packet_payload,
                   finding_payload, report_payload, updated_at
            FROM atlas_research.research_workflow_attempts
            WHERE tenant_id = %s AND workspace_id = %s AND workflow_id = %s
            """,
            (command.tenant_id, command.workspace_id, workflow_id),
        )
        if row is None:
            return None
        return {
            "workflow_id": row[0],
            "query_id": row[1],
            "step": row[2],
            "run_id": row[3],
            "packet_id": row[4],
            "finding_task_id": row[5],
            "report_id": row[6],
            "detail": row[7],
            "title": row[8],
            "checkpoint": dict(row[9]),
            "query_payload": dict(row[10]) if row[10] is not None else None,
            "packet_payload": dict(row[11]) if row[11] is not None else None,
            "finding_payload": dict(row[12]) if row[12] is not None else None,
            "report_payload": dict(row[13]) if row[13] is not None else None,
            "updated_at": row[14],
        }

    def list_attempts(
        self, *, context: ArtifactCommandContext, limit: int = 50
    ) -> list[dict[str, Any]]:
        command = ArtifactCommandContext.model_validate(context)
        bound = max(1, min(limit, 200))
        with self._database.connect(autocommit=True) as connection:
            rows = connection.execute(
                """
                SELECT workflow_id, query_id, step, run_id, packet_id, finding_task_id,
                       report_id, detail, title, checkpoint, updated_at
                FROM atlas_research.research_workflow_attempts
                WHERE tenant_id = %s AND workspace_id = %s
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (command.tenant_id, command.workspace_id, bound),
            ).fetchall()
        return [
            {
                "workflow_id": row[0],
                "query_id": row[1],
                "step": row[2],
                "run_id": row[3],
                "packet_id": row[4],
                "finding_task_id": row[5],
                "report_id": row[6],
                "detail": row[7],
                "title": row[8],
                "checkpoint": dict(row[9]),
                "updated_at": row[10],
            }
            for row in rows
        ]


__all__ = ["WorkflowRepository"]
