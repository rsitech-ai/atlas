"""Assemble EvidencePacket or honest abstention from hybrid retrieval."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from rsi_atlas_contracts import (
    DataCutoffManifest,
    DocumentProcessingLifecycle,
    EvidenceCandidate,
    EvidencePacket,
    QueryFamily,
    ResearchQuery,
    RetrievalAbstention,
    RetrievalDataPlane,
    RetrievalOutcome,
    RetrievalPlan,
    RetrievalReplayRecord,
    RetrievalStep,
    data_cutoff_manifest_hash,
    evidence_packet_id,
    research_query_hash,
    retrieval_plan_hash,
    retrieval_run_id,
)
from rsi_atlas_contracts.artifact import ArtifactCommandContext
from rsi_atlas_storage.document_processing_repository import DocumentProcessingRepository

from rsi_atlas_retrieval.coverage import evaluate_coverage, should_abstain
from rsi_atlas_retrieval.fusion import FUSION_CONFIGURATION_HASH, fuse_candidates_rrf
from rsi_atlas_retrieval.rerank import rerank_fused_lexical
from rsi_atlas_retrieval.search import HybridCandidateGenerator, vector_literal

EmbedFn = Callable[[str], tuple[float, ...]]


class RetrievalServiceError(ValueError):
    """Raised when hybrid retrieval fails closed."""


class HybridRetrievalService:
    """Run hybrid retrieval against active publications (RRF + lexical rerank)."""

    def __init__(
        self,
        *,
        processing: DocumentProcessingRepository,
        embed_text: EmbedFn,
        generator: HybridCandidateGenerator | None = None,
        lexical_rerank: bool = True,
    ) -> None:
        self._processing = processing
        self._embed_text = embed_text
        self._generator = generator or HybridCandidateGenerator(processing=processing)
        self._lexical_rerank = lexical_rerank

    def build_default_plan(self, *, query: ResearchQuery) -> RetrievalPlan:
        steps = (
            RetrievalStep(
                step_id="dense_primary",
                data_plane=RetrievalDataPlane.DENSE_DOCUMENT,
                retriever="pgvector_dense_v1",
                query_text=query.text,
                top_k=40,
                required=True,
                expected_evidence="semantically related document passages",
            ),
            RetrievalStep(
                step_id="lexical_primary",
                data_plane=RetrievalDataPlane.LEXICAL,
                retriever="pg_fts_v1",
                query_text=query.text,
                top_k=40,
                required=True,
                expected_evidence="lexical and identifier-bearing passages",
            ),
            RetrievalStep(
                step_id="exact_identifiers",
                data_plane=RetrievalDataPlane.EXACT_IDENTIFIER,
                retriever="exact_identifier_v1",
                query_text=query.text,
                top_k=200,
                required=query.query_family is QueryFamily.EXACT_LOOKUP,
                expected_evidence="exact EVM/Solana/Bitcoin identifier hits",
            ),
        )
        plan_hash = retrieval_plan_hash(
            query_id=query.query_id,
            query_family=query.query_family,
            steps=steps,
        )
        return RetrievalPlan(
            plan_id=uuid4(),
            query_id=query.query_id,
            query_family=query.query_family,
            steps=steps,
            plan_hash=plan_hash,
        )

    def retrieve(
        self,
        *,
        query: ResearchQuery,
        plan: RetrievalPlan | None = None,
        now: datetime | None = None,
    ) -> EvidencePacket | RetrievalAbstention:
        recorded_at = now or datetime.now(UTC)
        active_plan = plan or self.build_default_plan(query=query)
        if active_plan.query_id != query.query_id:
            raise RetrievalServiceError("plan query_id mismatch")
        if active_plan.query_family is not query.query_family:
            raise RetrievalServiceError("plan query_family mismatch")

        cutoff = self._freeze_cutoff(context=query.context, query=query, as_of=query.as_of)
        run_id = retrieval_run_id(
            query_id=query.query_id,
            plan_hash=active_plan.plan_hash,
            cutoff_hash=cutoff.manifest_hash,
        )

        candidates_by_plane: dict[RetrievalDataPlane, tuple[EvidenceCandidate, ...]] = {}
        query_vector = vector_literal(self._embed_text(query.text))
        for document_version_id, chunk_set_id in zip(
            query.document_version_ids, query.chunk_set_ids, strict=True
        ):
            for step in active_plan.steps:
                if step.data_plane is RetrievalDataPlane.DENSE_DOCUMENT:
                    dense = self._generator.generate_dense(
                        context=query.context,
                        document_version_id=document_version_id,
                        chunk_set_id=chunk_set_id,
                        query_vector=query_vector,
                        top_k=step.top_k,
                    )
                    candidates_by_plane[step.data_plane] = (
                        candidates_by_plane.get(step.data_plane, ()) + dense
                    )
                elif step.data_plane is RetrievalDataPlane.LEXICAL:
                    lexical = self._generator.generate_lexical(
                        context=query.context,
                        document_version_id=document_version_id,
                        chunk_set_id=chunk_set_id,
                        query_text=step.query_text,
                        top_k=step.top_k,
                    )
                    candidates_by_plane[step.data_plane] = (
                        candidates_by_plane.get(step.data_plane, ()) + lexical
                    )
                elif step.data_plane is RetrievalDataPlane.EXACT_IDENTIFIER:
                    exact = self._generator.generate_exact(
                        context=query.context,
                        document_version_id=document_version_id,
                        chunk_set_id=chunk_set_id,
                        query_text=step.query_text,
                        top_k=step.top_k,
                    )
                    candidates_by_plane[step.data_plane] = (
                        candidates_by_plane.get(step.data_plane, ()) + exact
                    )
                else:
                    raise RetrievalServiceError(f"unsupported data plane {step.data_plane}")

        fused = fuse_candidates_rrf(
            candidates_by_plane=candidates_by_plane,
            query_family=query.query_family,
            final_k=20,
        )
        if self._lexical_rerank and fused:
            fused = rerank_fused_lexical(query=query.text, items=fused, final_k=20)
        coverage = evaluate_coverage(query_family=query.query_family, items=fused)
        if should_abstain(coverage) or not fused:
            return RetrievalAbstention(
                run_id=run_id,
                query_id=query.query_id,
                plan_hash=active_plan.plan_hash,
                cutoff=cutoff,
                coverage=coverage
                if coverage
                else evaluate_coverage(query_family=query.query_family, items=()),
                reason="insufficient evidence for material question",
                recorded_at=recorded_at,
            )

        packet_id = evidence_packet_id(
            run_id=run_id,
            plan_hash=active_plan.plan_hash,
            cutoff_hash=cutoff.manifest_hash,
            items=fused,
        )
        return EvidencePacket(
            packet_id=packet_id,
            run_id=run_id,
            query_id=query.query_id,
            plan_hash=active_plan.plan_hash,
            cutoff=cutoff,
            items=fused,
            coverage=coverage,
            recorded_at=recorded_at,
        )

    def build_replay_record(
        self,
        *,
        query: ResearchQuery,
        plan: RetrievalPlan,
        result: EvidencePacket | RetrievalAbstention,
    ) -> RetrievalReplayRecord:
        return RetrievalReplayRecord(
            run_id=result.run_id,
            query_hash=research_query_hash(query),
            plan_hash=plan.plan_hash,
            cutoff_hash=result.cutoff.manifest_hash,
            fusion_configuration_hash=FUSION_CONFIGURATION_HASH,
            packet_id=result.packet_id if isinstance(result, EvidencePacket) else None,
            outcome=(
                RetrievalOutcome.PACKET
                if isinstance(result, EvidencePacket)
                else RetrievalOutcome.ABSTAIN
            ),
            code_version="phase3-dev-1",
        )

    def _freeze_cutoff(
        self,
        *,
        context: ArtifactCommandContext,
        query: ResearchQuery,
        as_of: datetime,
    ) -> DataCutoffManifest:
        publication_ids: list[str] = []
        index_version_ids: list[UUID] = []
        for _document_version_id, chunk_set_id in zip(
            query.document_version_ids, query.chunk_set_ids, strict=True
        ):
            versions = self._processing.list_retrieval_index_versions(
                context=context, chunk_set_id=chunk_set_id
            )
            active = [row for row in versions if row["searchable"]]
            if not active:
                continue
            # Prefer the active pointer's index version.
            chosen = active[-1]
            index_version_id = chosen["index_version_id"]
            assert isinstance(index_version_id, UUID)
            manifest = self._processing.get_retrieval_publication_manifest(
                context=context,
                index_version_id=index_version_id,
                lifecycle=DocumentProcessingLifecycle.PUBLISHED,
            )
            if manifest is None:
                continue
            publication_ids.append(str(manifest["publication_id"]))
            index_version_ids.append(index_version_id)

        if not publication_ids:
            # Empty cutoff still needs valid shape for abstention; use sentinel hashes.
            # Callers get MISSING coverage when no active publications exist.
            dummy_pub = "publication:" + ("0" * 64)
            dummy_index = UUID("00000000-0000-4000-8000-000000000000")
            publication_ids = [dummy_pub]
            index_version_ids = [dummy_index]

        pub_tuple = tuple(publication_ids)
        idx_tuple = tuple(index_version_ids)
        return DataCutoffManifest(
            effective_as_of=as_of,
            document_cutoff=as_of,
            publication_ids=pub_tuple,
            index_version_ids=idx_tuple,
            staleness_findings=(),
            manifest_hash=data_cutoff_manifest_hash(
                effective_as_of=as_of,
                document_cutoff=as_of,
                publication_ids=pub_tuple,
                index_version_ids=idx_tuple,
                staleness_findings=(),
            ),
        )
