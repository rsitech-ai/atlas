"""Loopback research API contract tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from json import dumps
from pathlib import Path
from threading import Event
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from rsi_atlas_contracts import (
    ArtifactCommandContext,
    CitationBinding,
    CitationRole,
    ComponentRank,
    CoverageCell,
    CoverageStatus,
    DataCutoffManifest,
    EvidencePacket,
    FindingCompletionStatus,
    FusedEvidenceItem,
    QueryFamily,
    ReportDraft,
    ReportPublicationOutcome,
    ReportSection,
    ResearchAssertion,
    ResearchQuery,
    RetrievalAbstention,
    RetrievalDataPlane,
    ReviewAction,
    ReviewDecision,
    SpecialistFinding,
    SpecialistType,
    citation_binding_id,
    data_cutoff_manifest_hash,
    evidence_packet_id,
    report_draft_id,
    research_assertion_id,
    retrieval_run_id,
    specialist_finding_id,
)
from rsi_atlas_engine import research as research_module
from rsi_atlas_engine.api import create_app
from rsi_atlas_engine.research import ResearchFacade, ResearchServices
from rsi_atlas_recovery import SafeModeBlocked, SafeModeController, SafeModeStore
from rsi_atlas_research.workflow import WorkflowCheckpoint, WorkflowStep, workflow_id_for_query

TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000002")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000000003")
TRACE_ID = UUID("00000000-0000-4000-8000-000000000004")
QUERY_ID = UUID("00000000-0000-4000-8000-0000000000aa")
INDEX_VERSION_ID = UUID("00000000-0000-4000-8000-0000000000cc")
DECISION_ID = UUID("00000000-0000-4000-8000-0000000000dd")
DOCUMENT_VERSION = "canonical:" + ("a" * 64)
CHUNK_SET_ID = "chunkset:" + ("b" * 64)
CHUNK_ID = "chunk:" + ("c" * 64)
PUBLICATION_ID = "publication:" + ("d" * 64)
REPORT_ID = "report:" + ("a" * 64)
EXCERPT_HASH = "e" * 64
NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def _headers() -> dict[str, str]:
    return {
        "x-rsi-tenant-id": str(TENANT_ID),
        "x-rsi-actor-id": str(ACTOR_ID),
        "x-rsi-trace-id": str(TRACE_ID),
    }


def _context() -> ArtifactCommandContext:
    return ArtifactCommandContext(
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        trace_id=TRACE_ID,
    )


def _packet() -> EvidencePacket:
    cutoff_hash = data_cutoff_manifest_hash(
        effective_as_of=NOW,
        document_cutoff=NOW,
        publication_ids=(PUBLICATION_ID,),
        index_version_ids=(INDEX_VERSION_ID,),
        staleness_findings=(),
    )
    cutoff = DataCutoffManifest(
        effective_as_of=NOW,
        document_cutoff=NOW,
        publication_ids=(PUBLICATION_ID,),
        index_version_ids=(INDEX_VERSION_ID,),
        staleness_findings=(),
        manifest_hash=cutoff_hash,
    )
    plan_hash = "f" * 64
    run_id = retrieval_run_id(query_id=QUERY_ID, plan_hash=plan_hash, cutoff_hash=cutoff_hash)
    item = FusedEvidenceItem(
        chunk_id=CHUNK_ID,
        document_version_id=DOCUMENT_VERSION,
        chunk_set_id=CHUNK_SET_ID,
        publication_id=PUBLICATION_ID,
        index_version_id=INDEX_VERSION_ID,
        fusion_score=0.5,
        fusion_rank=1,
        reliability_score=0.8,
        component_ranks=(
            ComponentRank(data_plane=RetrievalDataPlane.LEXICAL, rank=1, raw_score=1.0),
        ),
        excerpt_hash=EXCERPT_HASH,
        text_preview="Token unlocks begin in 2027.",
    )
    return EvidencePacket(
        packet_id=evidence_packet_id(
            run_id=run_id,
            plan_hash=plan_hash,
            cutoff_hash=cutoff_hash,
            items=(item,),
        ),
        run_id=run_id,
        query_id=QUERY_ID,
        plan_hash=plan_hash,
        cutoff=cutoff,
        items=(item,),
        coverage=(
            CoverageCell(
                requirement_id="primary_document_evidence",
                status=CoverageStatus.SATISFIED,
                detail="ok",
            ),
        ),
        recorded_at=NOW,
    )


class FakeResearchService:
    def retrieve(self, *, query: ResearchQuery) -> EvidencePacket | RetrievalAbstention:
        if "missing" in query.text:
            cutoff_hash = data_cutoff_manifest_hash(
                effective_as_of=NOW,
                document_cutoff=NOW,
                publication_ids=(PUBLICATION_ID,),
                index_version_ids=(INDEX_VERSION_ID,),
                staleness_findings=(),
            )
            return RetrievalAbstention(
                run_id=retrieval_run_id(
                    query_id=query.query_id,
                    plan_hash="f" * 64,
                    cutoff_hash=cutoff_hash,
                ),
                query_id=query.query_id,
                plan_hash="f" * 64,
                cutoff=DataCutoffManifest(
                    effective_as_of=NOW,
                    document_cutoff=NOW,
                    publication_ids=(PUBLICATION_ID,),
                    index_version_ids=(INDEX_VERSION_ID,),
                    staleness_findings=(),
                    manifest_hash=cutoff_hash,
                ),
                coverage=(
                    CoverageCell(
                        requirement_id="primary_document_evidence",
                        status=CoverageStatus.MISSING,
                        detail="none",
                    ),
                ),
                reason="insufficient evidence for material question",
                recorded_at=NOW,
            )
        return _packet()

    def run_document_specialist(
        self,
        *,
        query: ResearchQuery,
        packet: EvidencePacket,
        subquestion: str | None = None,
    ) -> SpecialistFinding:
        del query, subquestion
        task_id = "task:" + ("1" * 64)
        return SpecialistFinding(
            finding_id=specialist_finding_id(
                task_id=task_id,
                answer=packet.items[0].text_preview,
                completion_status=FindingCompletionStatus.SUPPORTED,
                supporting_chunk_ids=(packet.items[0].chunk_id,),
            ),
            task_id=task_id,
            specialist_type=SpecialistType.DOCUMENT_EVIDENCE,
            answer=packet.items[0].text_preview,
            supporting_chunk_ids=(packet.items[0].chunk_id,),
            completion_status=FindingCompletionStatus.SUPPORTED,
            confidence=0.9,
            recorded_at=NOW,
        )

    def draft_report(
        self,
        *,
        query: ResearchQuery,
        packet: EvidencePacket,
        finding: SpecialistFinding,
        title: str,
    ) -> ReportDraft:
        assertion = ResearchAssertion(
            assertion_id=research_assertion_id(
                run_id=packet.run_id,
                finding_id=finding.finding_id,
                statement=finding.answer,
                supporting_chunk_ids=finding.supporting_chunk_ids,
            ),
            run_id=packet.run_id,
            finding_id=finding.finding_id,
            statement=finding.answer,
            supporting_chunk_ids=finding.supporting_chunk_ids,
            confidence=finding.confidence,
        )
        citation = CitationBinding(
            citation_id=citation_binding_id(
                assertion_id=assertion.assertion_id,
                chunk_id=finding.supporting_chunk_ids[0],
                role=CitationRole.DIRECT_SUPPORT,
                excerpt_hash=packet.items[0].excerpt_hash,
            ),
            assertion_id=assertion.assertion_id,
            chunk_id=finding.supporting_chunk_ids[0],
            role=CitationRole.DIRECT_SUPPORT,
            excerpt_hash=packet.items[0].excerpt_hash,
            locator="chunk:test",
        )
        return ReportDraft(
            report_id=report_draft_id(
                run_id=packet.run_id,
                title=title,
                version=1,
                assertions=(assertion,),
                citations=(citation,),
            ),
            run_id=packet.run_id,
            context=query.context,
            title=title,
            sections=(
                ReportSection(
                    section_id="findings",
                    title="Findings",
                    prose=finding.answer,
                    assertion_ids=(assertion.assertion_id,),
                ),
            ),
            assertions=(assertion,),
            citations=(citation,),
            outcome=ReportPublicationOutcome.AWAIT_ANALYST_REVIEW,
            version=1,
            recorded_at=NOW,
        )

    def review_report(
        self,
        *,
        query: ResearchQuery,
        report: ReportDraft,
        action: ReviewAction,
        rationale: str,
    ) -> ReviewDecision:
        del query
        return ReviewDecision(
            decision_id=DECISION_ID,
            report_id=report.report_id,
            context=report.context,
            action=action,
            rationale=rationale,
            recorded_at=NOW,
        )

    def start_workflow(self, *, query: ResearchQuery, title: str) -> dict[str, object]:
        checkpoint = WorkflowCheckpoint(
            workflow_id=workflow_id_for_query(query_id=query.query_id),
            query_id=query.query_id,
            step=WorkflowStep.AWAITING_HUMAN,
            report_id=REPORT_ID,
            updated_at=NOW,
            detail=title,
        )
        return {"checkpoint": checkpoint.model_dump(mode="json"), "interrupted": True}

    def resume_workflow(
        self,
        *,
        query: ResearchQuery,
        title: str,
        human_decision: ReviewDecision | None = None,
    ) -> dict[str, object]:
        del title
        step = WorkflowStep.COMPLETED if human_decision is not None else WorkflowStep.AWAITING_HUMAN
        checkpoint = WorkflowCheckpoint(
            workflow_id=workflow_id_for_query(query_id=query.query_id),
            query_id=query.query_id,
            step=step,
            report_id=REPORT_ID,
            updated_at=NOW,
        )
        return {
            "checkpoint": checkpoint.model_dump(mode="json"),
            "interrupted": human_decision is None,
        }

    def get_workflow(self, *, context: ArtifactCommandContext, workflow_id: UUID) -> object | None:
        del context, workflow_id
        return None

    def list_workflows(self, *, context: ArtifactCommandContext, limit: int = 50) -> list[object]:
        del context, limit
        return []


def test_research_retrieve_and_report_routes() -> None:
    client = TestClient(create_app(research_service=FakeResearchService()))
    query = ResearchQuery(
        context=_context(),
        query_id=QUERY_ID,
        text="Bitcoin unlock schedule",
        document_version_ids=(DOCUMENT_VERSION,),
        chunk_set_ids=(CHUNK_SET_ID,),
        as_of=NOW,
        query_family=QueryFamily.NARRATIVE_EXPLANATION,
        latency_budget_ms=5_000,
        context_budget_tokens=2_048,
    )
    retrieved = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/research:retrieve",
        headers=_headers(),
        json=query.model_dump(mode="json"),
    )
    assert retrieved.status_code == 200
    assert retrieved.json()["outcome"] == "packet"
    packet = EvidencePacket.model_validate_json(dumps(retrieved.json()))

    finding_response = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/research/specialist:document",
        headers=_headers(),
        json={"query": query.model_dump(mode="json"), "packet": packet.model_dump(mode="json")},
    )
    assert finding_response.status_code == 200
    finding = SpecialistFinding.model_validate_json(dumps(finding_response.json()))

    draft_response = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/research/reports:draft",
        headers=_headers(),
        json={
            "query": query.model_dump(mode="json"),
            "packet": packet.model_dump(mode="json"),
            "finding": finding.model_dump(mode="json"),
            "title": "Unlock note",
        },
    )
    assert draft_response.status_code == 200
    draft = ReportDraft.model_validate_json(dumps(draft_response.json()))

    review_response = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/research/reports/{draft.report_id}/review",
        headers=_headers(),
        json={
            "query": query.model_dump(mode="json"),
            "report": draft.model_dump(mode="json"),
            "action": "approve",
            "rationale": "Citations resolve.",
        },
    )
    assert review_response.status_code == 200
    assert review_response.json()["action"] == "approve"


def test_research_retrieve_can_abstain() -> None:
    client = TestClient(create_app(research_service=FakeResearchService()))
    query = ResearchQuery(
        context=_context(),
        query_id=QUERY_ID,
        text="missing evidence",
        document_version_ids=(DOCUMENT_VERSION,),
        chunk_set_ids=(CHUNK_SET_ID,),
        as_of=NOW,
        query_family=QueryFamily.NARRATIVE_EXPLANATION,
        latency_budget_ms=5_000,
        context_budget_tokens=2_048,
    )
    response = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/research:retrieve",
        headers=_headers(),
        json=query.model_dump(mode="json"),
    )
    assert response.status_code == 200
    assert response.json()["outcome"] == "abstain"


def test_research_workflow_start_and_resume_routes() -> None:
    client = TestClient(create_app(research_service=FakeResearchService()))
    query = ResearchQuery(
        context=_context(),
        query_id=QUERY_ID,
        text="Bitcoin unlock schedule",
        document_version_ids=(DOCUMENT_VERSION,),
        chunk_set_ids=(CHUNK_SET_ID,),
        as_of=NOW,
        query_family=QueryFamily.NARRATIVE_EXPLANATION,
        latency_budget_ms=5_000,
        context_budget_tokens=2_048,
    )
    started = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/research/workflows:start",
        headers=_headers(),
        json={"query": query.model_dump(mode="json"), "title": "Unlock note"},
    )
    assert started.status_code == 200
    body = started.json()
    assert body["interrupted"] is True
    assert body["checkpoint"]["step"] == "awaiting_human"
    workflow_id = body["checkpoint"]["workflow_id"]

    listed = client.get(
        f"/v1/workspaces/{WORKSPACE_ID}/research/workflows",
        headers=_headers(),
    )
    assert listed.status_code == 200

    decision = ReviewDecision(
        decision_id=DECISION_ID,
        report_id=REPORT_ID,
        context=_context(),
        action=ReviewAction.APPROVE,
        rationale="Citations resolve.",
        recorded_at=NOW,
    )
    resumed = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/research/workflows/{workflow_id}:resume",
        headers=_headers(),
        json={
            "query": query.model_dump(mode="json"),
            "title": "Unlock note",
            "human_decision": decision.model_dump(mode="json"),
        },
    )
    assert resumed.status_code == 200
    assert resumed.json()["checkpoint"]["step"] == "completed"
    assert resumed.json()["interrupted"] is False


def test_safe_mode_blocks_models_and_workflow_mutation_but_keeps_listing_readable(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RSI_ATLAS_DATA_ROOT", str(tmp_path / "runtime"))
    client = TestClient(
        create_app(
            status_factory=lambda: (_ for _ in ()).throw(RuntimeError("unused")),
            research_service=FakeResearchService(),
        )
    )
    query = ResearchQuery(
        context=_context(),
        query_id=QUERY_ID,
        text="Bitcoin unlock schedule",
        document_version_ids=(DOCUMENT_VERSION,),
        chunk_set_ids=(CHUNK_SET_ID,),
        as_of=NOW,
        query_family=QueryFamily.NARRATIVE_EXPLANATION,
        latency_budget_ms=5_000,
        context_budget_tokens=2_048,
    )
    assert (
        client.post("/v1/recovery/safe-mode:enter", json={"reason": "operator"}).status_code == 200
    )

    retrieval = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/research:retrieve",
        headers=_headers(),
        json=query.model_dump(mode="json"),
    )
    assert retrieval.status_code == 423
    assert retrieval.json() == {"detail": "Safe Mode blocks models."}

    started = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/research/workflows:start",
        headers=_headers(),
        json={"query": query.model_dump(mode="json"), "title": "Unlock note"},
    )
    assert started.status_code == 423
    assert started.json() == {"detail": "Safe Mode blocks workflow_resumption."}

    workflow_id = workflow_id_for_query(query_id=query.query_id)
    resumed = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/research/workflows/{workflow_id}:resume",
        headers=_headers(),
        json={"query": query.model_dump(mode="json"), "title": "Unlock note"},
    )
    assert resumed.status_code == 423
    assert resumed.json() == {"detail": "Safe Mode blocks workflow_resumption."}

    listed = client.get(
        f"/v1/workspaces/{WORKSPACE_ID}/research/workflows",
        headers=_headers(),
    )
    assert listed.status_code == 200
    assert listed.json() == {"workflows": []}


def test_research_facade_guards_direct_model_and_workflow_calls(
    tmp_path: Path,
) -> None:
    controller = SafeModeController(SafeModeStore(tmp_path / "runtime"))
    services = ResearchServices(
        orchestrator=FakeResearchService(),  # type: ignore[arg-type]
        database=object(),  # type: ignore[arg-type]
        workflow_repository=object(),  # type: ignore[arg-type]
        research_repository=object(),  # type: ignore[arg-type]
        safe_mode=controller,
    )
    research = ResearchFacade(services)
    query = ResearchQuery(
        context=_context(),
        query_id=QUERY_ID,
        text="Bitcoin unlock schedule",
        document_version_ids=(DOCUMENT_VERSION,),
        chunk_set_ids=(CHUNK_SET_ID,),
        as_of=NOW,
        query_family=QueryFamily.NARRATIVE_EXPLANATION,
        latency_budget_ms=5_000,
        context_budget_tokens=2_048,
    )
    controller.enter(reason="operator", entered_at=NOW)

    with pytest.raises(SafeModeBlocked, match="models"):
        research.retrieve(query=query)
    with pytest.raises(SafeModeBlocked, match="workflow_resumption"):
        research.start_workflow(query=query, title="Unlock note")


def test_lazy_embedder_initializes_once_under_concurrent_first_use(tmp_path: Path) -> None:
    controller = SafeModeController(SafeModeStore(tmp_path / "runtime"))
    resolver_entered = Event()
    release_resolver = Event()
    resolver_calls = 0

    class FakeEmbedder:
        def embed_text(self, text: str) -> tuple[float, ...]:
            del text
            return (1.0,)

    def resolve() -> FakeEmbedder:
        nonlocal resolver_calls
        resolver_calls += 1
        resolver_entered.set()
        assert release_resolver.wait(timeout=2)
        return FakeEmbedder()

    embedder = research_module._LazySafeModeEmbedder(  # type: ignore[attr-defined]
        safe_mode=controller,
        resolver=resolve,
    )
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(embedder.embed_text, "btc") for _ in range(8)]
        assert resolver_entered.wait(timeout=2)
        release_resolver.set()
        assert [future.result(timeout=2) for future in futures] == [(1.0,)] * 8

    assert resolver_calls == 1
