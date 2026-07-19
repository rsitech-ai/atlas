"""Research workflow interrupt/resume tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from rsi_atlas_contracts import (
    ArtifactCommandContext,
    CoverageCell,
    CoverageStatus,
    DataCutoffManifest,
    QueryFamily,
    ResearchQuery,
    RetrievalAbstention,
    data_cutoff_manifest_hash,
)
from rsi_atlas_research.workflow import (
    InMemoryWorkflowStore,
    ResearchWorkflow,
    WorkflowCheckpoint,
    WorkflowStep,
    workflow_id_for_query,
)

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
QUERY_ID = UUID("00000000-0000-4000-8000-0000000000aa")
PUBLICATION_ID = "publication:" + ("a" * 64)
INDEX_VERSION_ID = UUID("00000000-0000-4000-8000-0000000000cc")
RUN_ID = "retrievalrun:" + ("c" * 64)


class _AbstainOrchestrator:
    def retrieve(self, *, query: ResearchQuery, now: datetime | None = None) -> RetrievalAbstention:
        stamped = now or NOW
        cutoff_hash = data_cutoff_manifest_hash(
            effective_as_of=stamped,
            document_cutoff=stamped,
            publication_ids=(PUBLICATION_ID,),
            index_version_ids=(INDEX_VERSION_ID,),
            staleness_findings=(),
        )
        cutoff = DataCutoffManifest(
            effective_as_of=stamped,
            document_cutoff=stamped,
            publication_ids=(PUBLICATION_ID,),
            index_version_ids=(INDEX_VERSION_ID,),
            staleness_findings=(),
            manifest_hash=cutoff_hash,
        )
        return RetrievalAbstention(
            run_id=RUN_ID,
            query_id=query.query_id,
            plan_hash="d" * 64,
            cutoff=cutoff,
            coverage=(
                CoverageCell(
                    requirement_id="primary_evidence",
                    status=CoverageStatus.MISSING,
                    detail="no hits",
                ),
            ),
            reason="insufficient evidence for material question",
            recorded_at=stamped,
        )


def _query() -> ResearchQuery:
    ctx = ArtifactCommandContext(
        workspace_id=uuid4(),
        tenant_id=uuid4(),
        actor_id=uuid4(),
        trace_id=uuid4(),
    )
    return ResearchQuery(
        query_id=QUERY_ID,
        context=ctx,
        text="What changed in fee regime?",
        query_family=QueryFamily.NARRATIVE_EXPLANATION,
        subject_ids=("btc:fees",),
        document_version_ids=("canonical:" + "e" * 64,),
        chunk_set_ids=("chunkset:" + "f" * 64,),
        as_of=NOW,
        latency_budget_ms=5_000,
        context_budget_tokens=2048,
    )


def test_workflow_aborts_on_abstention() -> None:
    workflow = ResearchWorkflow(
        orchestrator=_AbstainOrchestrator(),  # type: ignore[arg-type]
        interrupt_after=None,
    )
    checkpoint = workflow.start(query=_query(), title="Fees")
    assert checkpoint.step is WorkflowStep.ABORTED
    assert checkpoint.run_id == RUN_ID


def test_workflow_store_roundtrip() -> None:
    store = InMemoryWorkflowStore()
    wf_id = workflow_id_for_query(query_id=QUERY_ID)
    checkpoint = WorkflowCheckpoint(
        workflow_id=wf_id,
        query_id=QUERY_ID,
        step=WorkflowStep.AWAITING_HUMAN,
        updated_at=NOW,
    )
    store.save(checkpoint)
    assert store.get(wf_id) == checkpoint
