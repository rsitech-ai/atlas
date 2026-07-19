"""Persist research runs, report drafts, and immutable review decisions."""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb
from rsi_atlas_contracts import (
    ArtifactCommandContext,
    EvidencePacket,
    ReportDraft,
    RetrievalAbstention,
    ReviewDecision,
)

from rsi_atlas_storage.database import PostgresDatabase


class RetrievalResearchRepository:
    """Append-oriented persistence for Phase 3 research artifacts."""

    def __init__(self, database: PostgresDatabase) -> None:
        self._database = database

    def save_run(
        self,
        *,
        context: ArtifactCommandContext,
        result: EvidencePacket | RetrievalAbstention,
    ) -> None:
        command = ArtifactCommandContext.model_validate(context)
        payload = result.model_dump(mode="json")
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO atlas_research.research_runs (
                    tenant_id, workspace_id, run_id, query_id, outcome,
                    plan_hash, cutoff_hash, payload, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, workspace_id, run_id) DO NOTHING
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    result.run_id,
                    result.query_id,
                    result.outcome.value,
                    result.plan_hash,
                    result.cutoff.manifest_hash,
                    Jsonb(payload),
                    result.recorded_at,
                ),
            )
            connection.commit()

    def get_run(self, *, context: ArtifactCommandContext, run_id: str) -> dict[str, Any] | None:
        command = ArtifactCommandContext.model_validate(context)
        row = self._database.fetch_one(
            """
            SELECT payload
            FROM atlas_research.research_runs
            WHERE tenant_id = %s AND workspace_id = %s AND run_id = %s
            """,
            (command.tenant_id, command.workspace_id, run_id),
        )
        if row is None:
            return None
        return dict(row[0])

    def save_report(self, *, context: ArtifactCommandContext, report: ReportDraft) -> None:
        command = ArtifactCommandContext.model_validate(context)
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO atlas_research.report_drafts (
                    tenant_id, workspace_id, report_id, run_id, version, payload, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, workspace_id, report_id) DO NOTHING
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    report.report_id,
                    report.run_id,
                    report.version,
                    Jsonb(report.model_dump(mode="json")),
                    report.recorded_at,
                ),
            )
            connection.commit()

    def get_report(
        self, *, context: ArtifactCommandContext, report_id: str
    ) -> dict[str, Any] | None:
        command = ArtifactCommandContext.model_validate(context)
        row = self._database.fetch_one(
            """
            SELECT payload
            FROM atlas_research.report_drafts
            WHERE tenant_id = %s AND workspace_id = %s AND report_id = %s
            """,
            (command.tenant_id, command.workspace_id, report_id),
        )
        if row is None:
            return None
        return dict(row[0])

    def save_review(self, *, context: ArtifactCommandContext, decision: ReviewDecision) -> None:
        command = ArtifactCommandContext.model_validate(context)
        with self._database.connect() as connection:
            connection.execute(
                """
                INSERT INTO atlas_research.review_decisions (
                    tenant_id, workspace_id, decision_id, report_id,
                    action, rationale, payload, recorded_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    command.tenant_id,
                    command.workspace_id,
                    decision.decision_id,
                    decision.report_id,
                    decision.action.value,
                    decision.rationale,
                    Jsonb(decision.model_dump(mode="json")),
                    decision.recorded_at,
                ),
            )
            connection.commit()

    def list_reviews(
        self, *, context: ArtifactCommandContext, report_id: str
    ) -> list[dict[str, Any]]:
        command = ArtifactCommandContext.model_validate(context)
        with self._database.connect(autocommit=True) as connection:
            rows = connection.execute(
                """
                SELECT decision_id, action, rationale, payload, recorded_at
                FROM atlas_research.review_decisions
                WHERE tenant_id = %s AND workspace_id = %s AND report_id = %s
                ORDER BY recorded_at ASC
                """,
                (command.tenant_id, command.workspace_id, report_id),
            ).fetchall()
        return [
            {
                "decision_id": row[0],
                "action": row[1],
                "rationale": row[2],
                "payload": dict(row[3]),
                "recorded_at": row[4],
            }
            for row in rows
        ]
