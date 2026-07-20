"""Wire research orchestrator + durable workflow from the local runtime."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Any
from uuid import UUID

from rsi_atlas_contracts import (
    ArtifactCommandContext,
    EvidencePacket,
    ReportDraft,
    ResearchQuery,
    RetrievalAbstention,
    ReviewAction,
    ReviewDecision,
    SafeModeCapability,
    SpecialistFinding,
)
from rsi_atlas_ingestion.embedding.resolve import Embedder, resolve_embedder
from rsi_atlas_recovery import SafeModeController
from rsi_atlas_research import (
    PostgresWorkflowStore,
    ResearchOrchestrator,
    ResearchWorkflow,
    WorkflowAttempt,
    WorkflowCheckpoint,
    WorkflowInterrupted,
)
from rsi_atlas_retrieval import HybridRetrievalService
from rsi_atlas_storage import (
    DatabaseSettings,
    DocumentProcessingRepository,
    MigrationRunner,
    PostgresDatabase,
    RetrievalResearchRepository,
    WorkflowRepository,
)

from rsi_atlas_engine.runtime import RuntimePaths
from rsi_atlas_engine.safe_mode import apply_or_verify_migrations, runtime_safe_mode

_DATABASE_CONNECT_TIMEOUT_SECONDS = 1
_DATABASE_STATEMENT_TIMEOUT_MS = 10_000
_DATABASE_LOCK_TIMEOUT_MS = 5_000
_DATABASE_TRANSACTION_TIMEOUT_MS = 15_000


class _LazySafeModeEmbedder:
    def __init__(
        self,
        *,
        safe_mode: SafeModeController,
        resolver: Callable[[], Embedder],
    ) -> None:
        self._safe_mode = safe_mode
        self._resolver = resolver
        self._lock = Lock()
        self._embedder: Embedder | None = None

    def embed_text(self, text: str) -> tuple[float, ...]:
        self._safe_mode.require(SafeModeCapability.MODELS)
        embedder = self._embedder
        if embedder is None:
            with self._lock:
                self._safe_mode.require(SafeModeCapability.MODELS)
                if self._embedder is None:
                    self._embedder = self._resolver()
                embedder = self._embedder
        return embedder.embed_text(text)


@dataclass(frozen=True, slots=True)
class ResearchServices:
    orchestrator: ResearchOrchestrator
    database: PostgresDatabase
    workflow_repository: WorkflowRepository
    research_repository: RetrievalResearchRepository
    safe_mode: SafeModeController

    @classmethod
    def from_environment(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        database_conninfo: str | None = None,
        safe_mode: SafeModeController | None = None,
    ) -> ResearchServices:
        values = os.environ if environ is None else environ
        paths = RuntimePaths.from_environment(environ=values)
        socket_directory = paths.data_root / "postgres" / "socket"
        conninfo = database_conninfo or (
            f"host='{socket_directory}' port=5432 user='atlas' dbname='atlas'"
        )
        settings = DatabaseSettings.from_conninfo(
            conninfo,
            connect_timeout_seconds=_DATABASE_CONNECT_TIMEOUT_SECONDS,
            statement_timeout_ms=_DATABASE_STATEMENT_TIMEOUT_MS,
            lock_timeout_ms=_DATABASE_LOCK_TIMEOUT_MS,
            transaction_timeout_ms=_DATABASE_TRANSACTION_TIMEOUT_MS,
        )
        database = PostgresDatabase(settings)
        controller = safe_mode or runtime_safe_mode(environ=values)
        apply_or_verify_migrations(
            MigrationRunner(database, paths.migration_root),
            controller,
        )
        processing = DocumentProcessingRepository(database)
        embedder = _LazySafeModeEmbedder(
            safe_mode=controller,
            resolver=resolve_embedder,
        )

        retrieval = HybridRetrievalService(
            processing=processing,
            embed_text=embedder.embed_text,
        )
        research_repository = RetrievalResearchRepository(database)
        orchestrator = ResearchOrchestrator(
            retrieval=retrieval,
            store=research_repository,  # type: ignore[arg-type]
        )
        return cls(
            orchestrator=orchestrator,
            database=database,
            workflow_repository=WorkflowRepository(database),
            research_repository=research_repository,
            safe_mode=controller,
        )

    def workflow_for(self, context: ArtifactCommandContext) -> ResearchWorkflow:
        store = PostgresWorkflowStore(
            repository=self.workflow_repository,
            context=context,
        )
        return ResearchWorkflow(orchestrator=self.orchestrator, store=store)


class ResearchFacade:
    """ResearchPort + workflow start/resume over durable Postgres attempts."""

    def __init__(self, services: ResearchServices) -> None:
        self._services = services

    def retrieve(self, *, query: ResearchQuery) -> EvidencePacket | RetrievalAbstention:
        self._services.safe_mode.require(SafeModeCapability.MODELS)
        return self._services.orchestrator.retrieve(query=query)

    def run_document_specialist(
        self,
        *,
        query: ResearchQuery,
        packet: EvidencePacket,
        subquestion: str | None = None,
    ) -> SpecialistFinding:
        self._services.safe_mode.require(SafeModeCapability.MODELS)
        return self._services.orchestrator.run_document_specialist(
            query=query,
            packet=packet,
            subquestion=subquestion,
        )

    def draft_report(
        self,
        *,
        query: ResearchQuery,
        packet: EvidencePacket,
        finding: SpecialistFinding,
        title: str,
    ) -> ReportDraft:
        self._services.safe_mode.require(SafeModeCapability.MODELS)
        return self._services.orchestrator.draft_report(
            query=query,
            packet=packet,
            finding=finding,
            title=title,
        )

    def review_report(
        self,
        *,
        query: ResearchQuery,
        report: ReportDraft,
        action: ReviewAction,
        rationale: str,
    ) -> ReviewDecision:
        return self._services.orchestrator.review_report(
            query=query,
            report=report,
            action=action,
            rationale=rationale,
        )

    def start_workflow(
        self, *, query: ResearchQuery, title: str, now: datetime | None = None
    ) -> dict[str, Any]:
        self._services.safe_mode.require(SafeModeCapability.WORKFLOW_RESUMPTION)
        workflow = self._services.workflow_for(query.context)
        try:
            checkpoint = workflow.start(query=query, title=title, now=now)
            return _workflow_response(checkpoint=checkpoint, interrupted=False)
        except WorkflowInterrupted as error:
            return _workflow_response(checkpoint=error.checkpoint, interrupted=True)

    def resume_workflow(
        self,
        *,
        query: ResearchQuery,
        title: str,
        human_decision: ReviewDecision | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        self._services.safe_mode.require(SafeModeCapability.WORKFLOW_RESUMPTION)
        workflow = self._services.workflow_for(query.context)
        try:
            checkpoint = workflow.resume(
                query=query,
                title=title,
                human_decision=human_decision,
                now=now,
            )
            return _workflow_response(checkpoint=checkpoint, interrupted=False)
        except WorkflowInterrupted as error:
            return _workflow_response(checkpoint=error.checkpoint, interrupted=True)

    def get_workflow(
        self, *, context: ArtifactCommandContext, workflow_id: UUID
    ) -> WorkflowAttempt | None:
        return self._services.workflow_for(context).get(workflow_id)

    def list_workflows(
        self, *, context: ArtifactCommandContext, limit: int = 50
    ) -> list[WorkflowAttempt]:
        return self._services.workflow_for(context).list(limit=limit)


def _workflow_response(*, checkpoint: WorkflowCheckpoint, interrupted: bool) -> dict[str, Any]:
    return {
        "checkpoint": checkpoint.model_dump(mode="json"),
        "interrupted": interrupted,
        "recorded_at": (checkpoint.updated_at or datetime.now(UTC)).isoformat(),
    }


__all__ = ["ResearchFacade", "ResearchServices"]
