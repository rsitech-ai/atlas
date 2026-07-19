"""Minimal durable research workflow interrupt/resume (no LangGraph)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from json import dumps
from typing import Literal, Protocol
from uuid import UUID, uuid4

from pydantic import Field
from rsi_atlas_contracts import (
    EvidencePacket,
    ReportDraft,
    ResearchQuery,
    RetrievalAbstention,
    ReviewDecision,
    SpecialistFinding,
)
from rsi_atlas_contracts.document_parsing import DocumentContractModel

from rsi_atlas_research.service import ResearchOrchestrator


class WorkflowStep(StrEnum):
    PLANNED = "planned"
    RETRIEVED = "retrieved"
    SPECIALIST_DONE = "specialist_done"
    DRAFTED = "drafted"
    AWAITING_HUMAN = "awaiting_human"
    COMPLETED = "completed"
    ABORTED = "aborted"


_LINEAR: tuple[WorkflowStep, ...] = (
    WorkflowStep.PLANNED,
    WorkflowStep.RETRIEVED,
    WorkflowStep.SPECIALIST_DONE,
    WorkflowStep.DRAFTED,
    WorkflowStep.AWAITING_HUMAN,
    WorkflowStep.COMPLETED,
)


class WorkflowCheckpoint(DocumentContractModel):
    schema_version: Literal["rsi-atlas.research-workflow.v1"] = "rsi-atlas.research-workflow.v1"
    workflow_id: UUID
    query_id: UUID
    step: WorkflowStep
    run_id: str | None = None
    packet_id: str | None = None
    finding_task_id: str | None = None
    report_id: str | None = None
    detail: str = Field(default="", max_length=512)
    updated_at: datetime


class WorkflowAttempt(DocumentContractModel):
    """Checkpoint plus optional payloads needed to resume after process restart."""

    schema_version: Literal["rsi-atlas.research-workflow-attempt.v1"] = (
        "rsi-atlas.research-workflow-attempt.v1"
    )
    checkpoint: WorkflowCheckpoint
    title: str = Field(default="", max_length=256)
    query: ResearchQuery | None = None
    packet: EvidencePacket | None = None
    finding: SpecialistFinding | None = None
    report: ReportDraft | None = None


def workflow_id_for_query(*, query_id: UUID, seed: str = "research_linear_v1") -> UUID:
    digest = sha256(f"{seed}:{query_id}".encode()).hexdigest()
    return UUID(digest[:32])


class WorkflowStore(Protocol):
    def save(self, attempt: WorkflowAttempt) -> None: ...

    def get(self, workflow_id: UUID) -> WorkflowAttempt | None: ...

    def list(self, *, limit: int = 50) -> list[WorkflowAttempt]: ...


class InMemoryWorkflowStore:
    """Process-local attempt store for development / tests."""

    def __init__(self) -> None:
        self._rows: dict[UUID, WorkflowAttempt] = {}

    def save(self, attempt: WorkflowAttempt) -> None:
        existing = self._rows.get(attempt.checkpoint.workflow_id)
        if existing is not None:
            # Preserve previously saved payloads when a later save omits them.
            attempt = attempt.model_copy(
                update={
                    "query": attempt.query or existing.query,
                    "packet": attempt.packet or existing.packet,
                    "finding": attempt.finding or existing.finding,
                    "report": attempt.report or existing.report,
                    "title": attempt.title or existing.title,
                }
            )
        self._rows[attempt.checkpoint.workflow_id] = attempt

    def get(self, workflow_id: UUID) -> WorkflowAttempt | None:
        return self._rows.get(workflow_id)

    def list(self, *, limit: int = 50) -> list[WorkflowAttempt]:
        rows = sorted(
            self._rows.values(),
            key=lambda item: item.checkpoint.updated_at,
            reverse=True,
        )
        return rows[: max(1, min(limit, 200))]


class PostgresWorkflowStore:
    """Postgres-backed attempt store (durable interrupt/resume)."""

    def __init__(self, *, repository: object, context: object) -> None:
        # repository: WorkflowRepository; context: ArtifactCommandContext
        # Typed loosely so research stays free of a hard storage package edge.
        self._repository = repository
        self._context = context

    def save(self, attempt: WorkflowAttempt) -> None:
        checkpoint = attempt.checkpoint
        self._repository.save_attempt(  # type: ignore[attr-defined]
            context=self._context,
            workflow_id=checkpoint.workflow_id,
            query_id=checkpoint.query_id,
            step=checkpoint.step.value,
            updated_at=checkpoint.updated_at,
            checkpoint=checkpoint.model_dump(mode="json"),
            title=attempt.title,
            detail=checkpoint.detail,
            run_id=checkpoint.run_id,
            packet_id=checkpoint.packet_id,
            finding_task_id=checkpoint.finding_task_id,
            report_id=checkpoint.report_id,
            query_payload=attempt.query.model_dump(mode="json") if attempt.query else None,
            packet_payload=attempt.packet.model_dump(mode="json") if attempt.packet else None,
            finding_payload=attempt.finding.model_dump(mode="json") if attempt.finding else None,
            report_payload=attempt.report.model_dump(mode="json") if attempt.report else None,
        )

    def get(self, workflow_id: UUID) -> WorkflowAttempt | None:
        row = self._repository.get_attempt(  # type: ignore[attr-defined]
            context=self._context, workflow_id=workflow_id
        )
        if row is None:
            return None
        return _attempt_from_row(row)

    def list(self, *, limit: int = 50) -> list[WorkflowAttempt]:
        rows = self._repository.list_attempts(  # type: ignore[attr-defined]
            context=self._context, limit=limit
        )
        # List rows omit optional payloads; checkpoint + title are enough for UI.
        return [
            WorkflowAttempt(
                checkpoint=WorkflowCheckpoint.model_validate_json(dumps(row["checkpoint"])),
                title=str(row.get("title") or ""),
            )
            for row in rows
        ]


def _attempt_from_row(row: dict[str, object]) -> WorkflowAttempt:
    checkpoint = WorkflowCheckpoint.model_validate_json(dumps(row["checkpoint"]))
    query = (
        ResearchQuery.model_validate_json(dumps(row["query_payload"]))
        if row.get("query_payload") is not None
        else None
    )
    packet = (
        EvidencePacket.model_validate_json(dumps(row["packet_payload"]))
        if row.get("packet_payload") is not None
        else None
    )
    finding = (
        SpecialistFinding.model_validate_json(dumps(row["finding_payload"]))
        if row.get("finding_payload") is not None
        else None
    )
    report = (
        ReportDraft.model_validate_json(dumps(row["report_payload"]))
        if row.get("report_payload") is not None
        else None
    )
    return WorkflowAttempt(
        checkpoint=checkpoint,
        title=str(row.get("title") or ""),
        query=query,
        packet=packet,
        finding=finding,
        report=report,
    )


class WorkflowInterrupted(RuntimeError):
    """Raised when a human interrupt pauses the linear DAG."""

    def __init__(self, checkpoint: WorkflowCheckpoint) -> None:
        super().__init__(f"workflow interrupted at {checkpoint.step.value}")
        self.checkpoint = checkpoint


class ResearchWorkflow:
    """Linear retrieve → specialist → draft → await human; resume from last step."""

    def __init__(
        self,
        *,
        orchestrator: ResearchOrchestrator,
        store: WorkflowStore | None = None,
        interrupt_after: WorkflowStep | None = WorkflowStep.DRAFTED,
    ) -> None:
        self._orchestrator = orchestrator
        self._store: WorkflowStore = store or InMemoryWorkflowStore()
        self._interrupt_after = interrupt_after

    def start(
        self,
        *,
        query: ResearchQuery,
        title: str,
        now: datetime | None = None,
    ) -> WorkflowCheckpoint:
        recorded = now or datetime.now(UTC)
        wf_id = workflow_id_for_query(query_id=query.query_id)
        checkpoint = WorkflowCheckpoint(
            workflow_id=wf_id,
            query_id=query.query_id,
            step=WorkflowStep.PLANNED,
            updated_at=recorded,
        )
        self._persist(checkpoint, query=query, title=title)
        return self.resume(query=query, title=title, now=recorded)

    def resume(
        self,
        *,
        query: ResearchQuery,
        title: str,
        now: datetime | None = None,
        human_decision: ReviewDecision | None = None,
    ) -> WorkflowCheckpoint:
        recorded = now or datetime.now(UTC)
        wf_id = workflow_id_for_query(query_id=query.query_id)
        attempt = self._store.get(wf_id)
        if attempt is None:
            checkpoint = WorkflowCheckpoint(
                workflow_id=wf_id,
                query_id=query.query_id,
                step=WorkflowStep.PLANNED,
                updated_at=recorded,
            )
            attempt = WorkflowAttempt(checkpoint=checkpoint, query=query, title=title)
        else:
            checkpoint = attempt.checkpoint
            title = title or attempt.title
            if attempt.query is None:
                attempt = attempt.model_copy(update={"query": query, "title": title})

        if checkpoint.step is WorkflowStep.COMPLETED:
            return checkpoint
        if checkpoint.step is WorkflowStep.ABORTED:
            raise RuntimeError("workflow aborted")

        if checkpoint.step is WorkflowStep.PLANNED:
            result = self._orchestrator.retrieve(query=query, now=recorded)
            if isinstance(result, RetrievalAbstention):
                checkpoint = checkpoint.model_copy(
                    update={
                        "step": WorkflowStep.ABORTED,
                        "run_id": result.run_id,
                        "detail": result.reason,
                        "updated_at": recorded,
                    }
                )
                self._persist(checkpoint, query=query, title=title)
                return checkpoint
            checkpoint = checkpoint.model_copy(
                update={
                    "step": WorkflowStep.RETRIEVED,
                    "run_id": result.run_id,
                    "packet_id": result.packet_id,
                    "updated_at": recorded,
                }
            )
            self._persist(checkpoint, query=query, title=title, packet=result)
            if self._should_interrupt(WorkflowStep.RETRIEVED):
                raise WorkflowInterrupted(checkpoint)

        if checkpoint.step is WorkflowStep.RETRIEVED:
            packet = self._require_packet(wf_id, checkpoint)
            finding = self._orchestrator.run_document_specialist(
                query=query, packet=packet, now=recorded
            )
            checkpoint = checkpoint.model_copy(
                update={
                    "step": WorkflowStep.SPECIALIST_DONE,
                    "finding_task_id": finding.task_id,
                    "updated_at": recorded,
                }
            )
            self._persist(checkpoint, query=query, title=title, packet=packet, finding=finding)
            if self._should_interrupt(WorkflowStep.SPECIALIST_DONE):
                raise WorkflowInterrupted(checkpoint)

        if checkpoint.step is WorkflowStep.SPECIALIST_DONE:
            packet = self._require_packet(wf_id, checkpoint)
            finding = self._require_finding(wf_id, checkpoint)
            report = self._orchestrator.draft_report(
                query=query, packet=packet, finding=finding, title=title, now=recorded
            )
            checkpoint = checkpoint.model_copy(
                update={
                    "step": WorkflowStep.DRAFTED,
                    "report_id": report.report_id,
                    "updated_at": recorded,
                }
            )
            self._persist(
                checkpoint,
                query=query,
                title=title,
                packet=packet,
                finding=finding,
                report=report,
            )
            if self._should_interrupt(WorkflowStep.DRAFTED):
                checkpoint = checkpoint.model_copy(
                    update={"step": WorkflowStep.AWAITING_HUMAN, "updated_at": recorded}
                )
                self._persist(
                    checkpoint,
                    query=query,
                    title=title,
                    packet=packet,
                    finding=finding,
                    report=report,
                )
                raise WorkflowInterrupted(checkpoint)

        if checkpoint.step is WorkflowStep.AWAITING_HUMAN:
            if human_decision is None:
                raise WorkflowInterrupted(checkpoint)
            if human_decision.report_id != checkpoint.report_id:
                raise RuntimeError("review decision report_id mismatch")
            report = self._require_report(wf_id, checkpoint)
            self._orchestrator.review_report(
                query=query,
                report=report,
                action=human_decision.action,
                rationale=human_decision.rationale,
                now=recorded,
            )
            checkpoint = checkpoint.model_copy(
                update={"step": WorkflowStep.COMPLETED, "updated_at": recorded}
            )
            self._persist(checkpoint, query=query, title=title, report=report)
            return checkpoint

        if checkpoint.step is WorkflowStep.DRAFTED:
            checkpoint = checkpoint.model_copy(
                update={"step": WorkflowStep.AWAITING_HUMAN, "updated_at": recorded}
            )
            self._persist(checkpoint, query=query, title=title)
            raise WorkflowInterrupted(checkpoint)

        return checkpoint

    def get(self, workflow_id: UUID) -> WorkflowAttempt | None:
        return self._store.get(workflow_id)

    def list(self, *, limit: int = 50) -> list[WorkflowAttempt]:
        return self._store.list(limit=limit)

    def _persist(
        self,
        checkpoint: WorkflowCheckpoint,
        *,
        query: ResearchQuery | None = None,
        title: str = "",
        packet: EvidencePacket | None = None,
        finding: SpecialistFinding | None = None,
        report: ReportDraft | None = None,
    ) -> None:
        self._store.save(
            WorkflowAttempt(
                checkpoint=checkpoint,
                title=title,
                query=query,
                packet=packet,
                finding=finding,
                report=report,
            )
        )

    def _should_interrupt(self, step: WorkflowStep) -> bool:
        if self._interrupt_after is None:
            return False
        try:
            return _LINEAR.index(step) >= _LINEAR.index(self._interrupt_after)
        except ValueError:
            return False

    def _require_packet(self, workflow_id: UUID, checkpoint: WorkflowCheckpoint) -> EvidencePacket:
        attempt = self._store.get(workflow_id)
        if (
            checkpoint.packet_id is None
            or attempt is None
            or attempt.packet is None
            or attempt.packet.packet_id != checkpoint.packet_id
        ):
            raise RuntimeError("missing packet for resume; re-run retrieve step")
        return attempt.packet

    def _require_finding(
        self, workflow_id: UUID, checkpoint: WorkflowCheckpoint
    ) -> SpecialistFinding:
        attempt = self._store.get(workflow_id)
        if (
            checkpoint.finding_task_id is None
            or attempt is None
            or attempt.finding is None
            or attempt.finding.task_id != checkpoint.finding_task_id
        ):
            raise RuntimeError("missing finding for resume")
        return attempt.finding

    def _require_report(self, workflow_id: UUID, checkpoint: WorkflowCheckpoint) -> ReportDraft:
        attempt = self._store.get(workflow_id)
        if (
            checkpoint.report_id is None
            or attempt is None
            or attempt.report is None
            or attempt.report.report_id != checkpoint.report_id
        ):
            raise RuntimeError("missing report for resume")
        return attempt.report


def checkpoint_fingerprint(checkpoint: WorkflowCheckpoint) -> str:
    return sha256(
        dumps(checkpoint.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def new_workflow_id() -> UUID:
    return uuid4()


__all__ = [
    "InMemoryWorkflowStore",
    "PostgresWorkflowStore",
    "ResearchWorkflow",
    "WorkflowAttempt",
    "WorkflowCheckpoint",
    "WorkflowInterrupted",
    "WorkflowStep",
    "WorkflowStore",
    "checkpoint_fingerprint",
    "new_workflow_id",
    "workflow_id_for_query",
]
