"""Minimal durable research workflow interrupt/resume (no LangGraph)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from json import dumps
from typing import Literal
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


def workflow_id_for_query(*, query_id: UUID, seed: str = "research_linear_v1") -> UUID:
    digest = sha256(f"{seed}:{query_id}".encode()).hexdigest()
    return UUID(digest[:32])


class InMemoryWorkflowStore:
    """Process-local checkpoint store for development / tests.

    ponytail: ceiling=not Postgres-durable; upgrade=migration research_workflow_attempts
    """

    def __init__(self) -> None:
        self._rows: dict[UUID, WorkflowCheckpoint] = {}

    def save(self, checkpoint: WorkflowCheckpoint) -> None:
        self._rows[checkpoint.workflow_id] = checkpoint

    def get(self, workflow_id: UUID) -> WorkflowCheckpoint | None:
        return self._rows.get(workflow_id)


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
        store: InMemoryWorkflowStore | None = None,
        interrupt_after: WorkflowStep | None = WorkflowStep.DRAFTED,
    ) -> None:
        self._orchestrator = orchestrator
        self._store = store or InMemoryWorkflowStore()
        self._interrupt_after = interrupt_after
        self._packets: dict[str, EvidencePacket] = {}
        self._findings: dict[str, SpecialistFinding] = {}
        self._reports: dict[str, ReportDraft] = {}

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
        self._store.save(checkpoint)
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
        checkpoint = self._store.get(wf_id)
        if checkpoint is None:
            checkpoint = WorkflowCheckpoint(
                workflow_id=wf_id,
                query_id=query.query_id,
                step=WorkflowStep.PLANNED,
                updated_at=recorded,
            )
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
                self._store.save(checkpoint)
                return checkpoint
            self._packets[result.packet_id] = result
            checkpoint = checkpoint.model_copy(
                update={
                    "step": WorkflowStep.RETRIEVED,
                    "run_id": result.run_id,
                    "packet_id": result.packet_id,
                    "updated_at": recorded,
                }
            )
            self._store.save(checkpoint)
            if self._should_interrupt(WorkflowStep.RETRIEVED):
                raise WorkflowInterrupted(checkpoint)

        if checkpoint.step is WorkflowStep.RETRIEVED:
            packet = self._require_packet(checkpoint)
            finding = self._orchestrator.run_document_specialist(
                query=query, packet=packet, now=recorded
            )
            self._findings[finding.task_id] = finding
            checkpoint = checkpoint.model_copy(
                update={
                    "step": WorkflowStep.SPECIALIST_DONE,
                    "finding_task_id": finding.task_id,
                    "updated_at": recorded,
                }
            )
            self._store.save(checkpoint)
            if self._should_interrupt(WorkflowStep.SPECIALIST_DONE):
                raise WorkflowInterrupted(checkpoint)

        if checkpoint.step is WorkflowStep.SPECIALIST_DONE:
            packet = self._require_packet(checkpoint)
            finding = self._require_finding(checkpoint)
            report = self._orchestrator.draft_report(
                query=query, packet=packet, finding=finding, title=title, now=recorded
            )
            self._reports[report.report_id] = report
            checkpoint = checkpoint.model_copy(
                update={
                    "step": WorkflowStep.DRAFTED,
                    "report_id": report.report_id,
                    "updated_at": recorded,
                }
            )
            self._store.save(checkpoint)
            if self._should_interrupt(WorkflowStep.DRAFTED):
                checkpoint = checkpoint.model_copy(
                    update={"step": WorkflowStep.AWAITING_HUMAN, "updated_at": recorded}
                )
                self._store.save(checkpoint)
                raise WorkflowInterrupted(checkpoint)

        if checkpoint.step is WorkflowStep.AWAITING_HUMAN:
            if human_decision is None:
                raise WorkflowInterrupted(checkpoint)
            if human_decision.report_id != checkpoint.report_id:
                raise RuntimeError("review decision report_id mismatch")
            checkpoint = checkpoint.model_copy(
                update={"step": WorkflowStep.COMPLETED, "updated_at": recorded}
            )
            self._store.save(checkpoint)
            return checkpoint

        if checkpoint.step is WorkflowStep.DRAFTED:
            checkpoint = checkpoint.model_copy(
                update={"step": WorkflowStep.AWAITING_HUMAN, "updated_at": recorded}
            )
            self._store.save(checkpoint)
            raise WorkflowInterrupted(checkpoint)

        return checkpoint

    def _should_interrupt(self, step: WorkflowStep) -> bool:
        if self._interrupt_after is None:
            return False
        try:
            return _LINEAR.index(step) >= _LINEAR.index(self._interrupt_after)
        except ValueError:
            return False

    def _require_packet(self, checkpoint: WorkflowCheckpoint) -> EvidencePacket:
        if checkpoint.packet_id is None or checkpoint.packet_id not in self._packets:
            raise RuntimeError("missing packet for resume; re-run retrieve step")
        return self._packets[checkpoint.packet_id]

    def _require_finding(self, checkpoint: WorkflowCheckpoint) -> SpecialistFinding:
        if checkpoint.finding_task_id is None or checkpoint.finding_task_id not in self._findings:
            raise RuntimeError("missing finding for resume")
        return self._findings[checkpoint.finding_task_id]


def checkpoint_fingerprint(checkpoint: WorkflowCheckpoint) -> str:
    return sha256(
        dumps(checkpoint.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def new_workflow_id() -> UUID:
    return uuid4()


__all__ = [
    "InMemoryWorkflowStore",
    "ResearchWorkflow",
    "WorkflowCheckpoint",
    "WorkflowInterrupted",
    "WorkflowStep",
    "checkpoint_fingerprint",
    "new_workflow_id",
    "workflow_id_for_query",
]
