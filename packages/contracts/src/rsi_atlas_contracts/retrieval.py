"""Strict hybrid retrieval contracts for Phase 3 (§16 development slice)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from json import dumps
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, StrictBool, StrictFloat, StrictInt, field_validator, model_validator

from rsi_atlas_contracts.artifact import ArtifactCommandContext
from rsi_atlas_contracts.document_parsing import DocumentContractModel

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_CHUNK_ID_PATTERN = r"^chunk:[0-9a-f]{64}$"
_CANONICAL_ID_PATTERN = r"^canonical:[0-9a-f]{64}$"
_CHUNK_SET_ID_PATTERN = r"^chunkset:[0-9a-f]{64}$"
_PUBLICATION_ID_PATTERN = r"^publication:[0-9a-f]{64}$"
_RUN_ID_PATTERN = r"^retrievalrun:[0-9a-f]{64}$"
_PACKET_ID_PATTERN = r"^evidencepacket:[0-9a-f]{64}$"
_CANDIDATE_ID_PATTERN = r"^candidate:[0-9a-f]{64}$"
_SUBJECT_PATTERN = r"^[a-z0-9][a-z0-9:_./-]{0,127}$"
_IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"


class QueryFamily(StrEnum):
    EXACT_LOOKUP = "exact_lookup"
    NARRATIVE_EXPLANATION = "narrative_explanation"
    NUMERICAL_ANALYSIS = "numerical_analysis"
    TEMPORAL_TREND = "temporal_trend"
    CROSS_PROTOCOL_COMPARISON = "cross_protocol_comparison"
    CONTRADICTION_VERIFICATION = "contradiction_verification"
    EVENT_INVESTIGATION = "event_investigation"
    EXPLORATORY_RESEARCH = "exploratory_research"


class RetrievalDataPlane(StrEnum):
    DENSE_DOCUMENT = "dense_document"
    LEXICAL = "lexical"
    EXACT_IDENTIFIER = "exact_identifier"
    STRUCTURED_RELATIONAL = "structured_relational"
    TIME_SERIES = "time_series"
    EVIDENCE_EDGE = "evidence_edge"
    CHAIN_SNAPSHOT = "chain_snapshot"
    DEVELOPMENT = "development"
    CALCULATION = "calculation"


# Development slice: only document planes backed by Phase 2D publications.
DEVELOPMENT_RETRIEVAL_PLANES = frozenset(
    {
        RetrievalDataPlane.DENSE_DOCUMENT,
        RetrievalDataPlane.LEXICAL,
        RetrievalDataPlane.EXACT_IDENTIFIER,
    }
)


class EvidenceItemKind(StrEnum):
    SOURCE_CONTENT = "SOURCE_CONTENT"
    GENERATED_METADATA = "GENERATED_METADATA"
    DETERMINISTIC_CALCULATION = "DETERMINISTIC_CALCULATION"
    ANALYST_NOTE = "ANALYST_NOTE"
    MODEL_INFERENCE = "MODEL_INFERENCE"


class CoverageStatus(StrEnum):
    SATISFIED = "satisfied"
    PARTIALLY_SATISFIED = "partially_satisfied"
    CONFLICTED = "conflicted"
    STALE = "stale"
    MISSING = "missing"
    NOT_APPLICABLE = "not_applicable"


class RetrievalOutcome(StrEnum):
    PACKET = "packet"
    ABSTAIN = "abstain"


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


def _canonical_json(payload: object) -> str:
    return dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class ResearchQuery(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    context: ArtifactCommandContext
    query_id: UUID
    text: str = Field(min_length=1, max_length=4_000)
    subject_ids: tuple[str, ...] = Field(default=(), max_length=32)
    document_version_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    chunk_set_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    as_of: datetime
    query_family: QueryFamily
    latency_budget_ms: StrictInt = Field(ge=1, le=600_000)
    context_budget_tokens: StrictInt = Field(ge=64, le=128_000)

    @field_validator("as_of")
    @classmethod
    def as_of_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="as_of")

    @field_validator("text")
    @classmethod
    def text_is_clean(cls, value: str) -> str:
        if value != value.strip() or "\x00" in value:
            raise ValueError("query text is invalid")
        return value

    @field_validator("subject_ids")
    @classmethod
    def subjects_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("subject_ids must be unique")
        for item in value:
            if not re.fullmatch(_SUBJECT_PATTERN, item):
                raise ValueError("subject_id format is invalid")
        return value

    @field_validator("document_version_ids")
    @classmethod
    def document_ids_valid(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("document_version_ids must be unique")
        for item in value:
            if not re.fullmatch(_CANONICAL_ID_PATTERN, item):
                raise ValueError("document_version_id format is invalid")
        return value

    @field_validator("chunk_set_ids")
    @classmethod
    def chunk_set_ids_valid(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("chunk_set_ids must be unique")
        for item in value:
            if not re.fullmatch(_CHUNK_SET_ID_PATTERN, item):
                raise ValueError("chunk_set_id format is invalid")
        return value


class DataCutoffManifest(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    effective_as_of: datetime
    document_cutoff: datetime
    publication_ids: tuple[str, ...] = Field(min_length=1, max_length=64)
    index_version_ids: tuple[UUID, ...] = Field(min_length=1, max_length=64)
    staleness_findings: tuple[str, ...] = ()
    manifest_hash: str = Field(pattern=_SHA256_PATTERN)

    @field_validator("effective_as_of", "document_cutoff")
    @classmethod
    def cutoff_times_are_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="cutoff")

    @model_validator(mode="after")
    def hash_matches_body(self) -> Self:
        expected = data_cutoff_manifest_hash(
            effective_as_of=self.effective_as_of,
            document_cutoff=self.document_cutoff,
            publication_ids=self.publication_ids,
            index_version_ids=self.index_version_ids,
            staleness_findings=self.staleness_findings,
        )
        if self.manifest_hash != expected:
            raise ValueError("manifest_hash does not match deterministic identity")
        if len(set(self.publication_ids)) != len(self.publication_ids):
            raise ValueError("publication_ids must be unique")
        if len(set(self.index_version_ids)) != len(self.index_version_ids):
            raise ValueError("index_version_ids must be unique")
        for publication_id in self.publication_ids:
            if not re.fullmatch(_PUBLICATION_ID_PATTERN, publication_id):
                raise ValueError("publication_id format is invalid")
        return self


class RetrievalStep(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    step_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    data_plane: RetrievalDataPlane
    retriever: str = Field(pattern=_IDENTIFIER_PATTERN)
    query_text: str = Field(min_length=1, max_length=4_000)
    top_k: StrictInt = Field(ge=1, le=200)
    required: StrictBool = True
    expected_evidence: str = Field(min_length=1, max_length=240)

    @model_validator(mode="after")
    def development_plane_allowed(self) -> Self:
        if self.data_plane not in DEVELOPMENT_RETRIEVAL_PLANES:
            raise ValueError(
                f"data plane {self.data_plane} is blocked until later phases "
                "(development slice allows dense/lexical/exact only)"
            )
        return self


class RetrievalPlan(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    plan_id: UUID
    query_id: UUID
    query_family: QueryFamily
    steps: tuple[RetrievalStep, ...] = Field(min_length=1, max_length=32)
    plan_hash: str = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def plan_is_consistent(self) -> Self:
        step_ids = tuple(step.step_id for step in self.steps)
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("retrieval step identifiers must be unique")
        expected = retrieval_plan_hash(
            query_id=self.query_id,
            query_family=self.query_family,
            steps=self.steps,
        )
        if self.plan_hash != expected:
            raise ValueError("plan_hash does not match deterministic identity")
        return self


class EvidenceCandidate(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    candidate_id: str = Field(pattern=_CANDIDATE_ID_PATTERN)
    chunk_id: str = Field(pattern=_CHUNK_ID_PATTERN)
    document_version_id: str = Field(pattern=_CANONICAL_ID_PATTERN)
    chunk_set_id: str = Field(pattern=_CHUNK_SET_ID_PATTERN)
    publication_id: str = Field(pattern=_PUBLICATION_ID_PATTERN)
    index_version_id: UUID
    data_plane: RetrievalDataPlane
    item_kind: EvidenceItemKind = EvidenceItemKind.SOURCE_CONTENT
    raw_score: StrictFloat
    rank: StrictInt = Field(ge=1, le=10_000)
    reliability_score: StrictFloat = Field(ge=0.0, le=1.0)
    excerpt_hash: str = Field(pattern=_SHA256_PATTERN)
    text_preview: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def candidate_rules(self) -> Self:
        if self.data_plane not in DEVELOPMENT_RETRIEVAL_PLANES:
            raise ValueError("candidate data plane is outside development slice")
        if self.item_kind is EvidenceItemKind.SOURCE_CONTENT and not self.text_preview.strip():
            raise ValueError("source content requires a text preview")
        if not (self.raw_score == self.raw_score) or abs(self.raw_score) == float("inf"):
            raise ValueError("raw_score must be finite")
        expected = evidence_candidate_id(
            chunk_id=self.chunk_id,
            data_plane=self.data_plane,
            index_version_id=self.index_version_id,
            rank=self.rank,
        )
        if self.candidate_id != expected:
            raise ValueError("candidate_id does not match deterministic identity")
        return self


class ComponentRank(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    data_plane: RetrievalDataPlane
    rank: StrictInt = Field(ge=1, le=10_000)
    raw_score: StrictFloat


class FusedEvidenceItem(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    chunk_id: str = Field(pattern=_CHUNK_ID_PATTERN)
    document_version_id: str = Field(pattern=_CANONICAL_ID_PATTERN)
    chunk_set_id: str = Field(pattern=_CHUNK_SET_ID_PATTERN)
    publication_id: str = Field(pattern=_PUBLICATION_ID_PATTERN)
    index_version_id: UUID
    item_kind: EvidenceItemKind = EvidenceItemKind.SOURCE_CONTENT
    fusion_score: StrictFloat
    fusion_rank: StrictInt = Field(ge=1, le=10_000)
    reliability_score: StrictFloat = Field(ge=0.0, le=1.0)
    component_ranks: tuple[ComponentRank, ...] = Field(min_length=1, max_length=8)
    excerpt_hash: str = Field(pattern=_SHA256_PATTERN)
    text_preview: str = Field(min_length=1, max_length=500)


class CoverageCell(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    requirement_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    status: CoverageStatus
    detail: str = Field(min_length=1, max_length=240)


class EvidencePacket(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    packet_id: str = Field(pattern=_PACKET_ID_PATTERN)
    run_id: str = Field(pattern=_RUN_ID_PATTERN)
    query_id: UUID
    plan_hash: str = Field(pattern=_SHA256_PATTERN)
    cutoff: DataCutoffManifest
    items: tuple[FusedEvidenceItem, ...] = Field(min_length=1, max_length=64)
    coverage: tuple[CoverageCell, ...] = Field(min_length=1, max_length=64)
    missing_evidence: tuple[str, ...] = ()
    unresolved_conflicts: tuple[str, ...] = ()
    outcome: Literal[RetrievalOutcome.PACKET] = RetrievalOutcome.PACKET
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="recorded_at")

    @model_validator(mode="after")
    def packet_is_consistent(self) -> Self:
        expected = evidence_packet_id(
            run_id=self.run_id,
            plan_hash=self.plan_hash,
            cutoff_hash=self.cutoff.manifest_hash,
            items=self.items,
        )
        if self.packet_id != expected:
            raise ValueError("packet_id does not match deterministic identity")
        ranks = tuple(item.fusion_rank for item in self.items)
        if ranks != tuple(range(1, len(self.items) + 1)):
            raise ValueError("fusion_rank values must be contiguous starting at 1")
        return self


class RetrievalAbstention(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: str = Field(pattern=_RUN_ID_PATTERN)
    query_id: UUID
    plan_hash: str = Field(pattern=_SHA256_PATTERN)
    cutoff: DataCutoffManifest
    coverage: tuple[CoverageCell, ...] = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=240)
    outcome: Literal[RetrievalOutcome.ABSTAIN] = RetrievalOutcome.ABSTAIN
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="recorded_at")


class RetrievalReplayRecord(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    run_id: str = Field(pattern=_RUN_ID_PATTERN)
    query_hash: str = Field(pattern=_SHA256_PATTERN)
    plan_hash: str = Field(pattern=_SHA256_PATTERN)
    cutoff_hash: str = Field(pattern=_SHA256_PATTERN)
    fusion_configuration_hash: str = Field(pattern=_SHA256_PATTERN)
    packet_id: str | None = Field(default=None, pattern=_PACKET_ID_PATTERN)
    outcome: RetrievalOutcome
    code_version: str = Field(min_length=1, max_length=64)


def data_cutoff_manifest_hash(
    *,
    effective_as_of: datetime,
    document_cutoff: datetime,
    publication_ids: tuple[str, ...],
    index_version_ids: tuple[UUID, ...],
    staleness_findings: tuple[str, ...],
) -> str:
    body = {
        "document_cutoff": document_cutoff.isoformat(),
        "effective_as_of": effective_as_of.isoformat(),
        "index_version_ids": [str(item) for item in index_version_ids],
        "publication_ids": list(publication_ids),
        "staleness_findings": list(staleness_findings),
    }
    return sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def retrieval_plan_hash(
    *,
    query_id: UUID,
    query_family: QueryFamily,
    steps: tuple[RetrievalStep, ...],
) -> str:
    body = {
        "query_family": query_family.value,
        "query_id": str(query_id),
        "steps": [step.model_dump(mode="json") for step in steps],
    }
    return sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def evidence_candidate_id(
    *,
    chunk_id: str,
    data_plane: RetrievalDataPlane,
    index_version_id: UUID,
    rank: int,
) -> str:
    material = f"{chunk_id}|{data_plane.value}|{index_version_id}|{rank}"
    return f"candidate:{sha256(material.encode('utf-8')).hexdigest()}"


def evidence_packet_id(
    *,
    run_id: str,
    plan_hash: str,
    cutoff_hash: str,
    items: tuple[FusedEvidenceItem, ...],
) -> str:
    body = {
        "cutoff_hash": cutoff_hash,
        "items": [item.model_dump(mode="json") for item in items],
        "plan_hash": plan_hash,
        "run_id": run_id,
    }
    return f"evidencepacket:{sha256(_canonical_json(body).encode('utf-8')).hexdigest()}"


def retrieval_run_id(
    *,
    query_id: UUID,
    plan_hash: str,
    cutoff_hash: str,
) -> str:
    material = f"{query_id}|{plan_hash}|{cutoff_hash}"
    return f"retrievalrun:{sha256(material.encode('utf-8')).hexdigest()}"


def research_query_hash(query: ResearchQuery) -> str:
    return sha256(_canonical_json(query.model_dump(mode="json")).encode("utf-8")).hexdigest()
