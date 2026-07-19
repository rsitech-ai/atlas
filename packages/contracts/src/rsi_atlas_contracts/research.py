"""Strict research / assertion / citation / report contracts for Phase 3 (ss17-18)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from json import dumps
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, StrictFloat, StrictInt, field_validator, model_validator

from rsi_atlas_contracts.artifact import ArtifactCommandContext
from rsi_atlas_contracts.document_parsing import DocumentContractModel
from rsi_atlas_contracts.retrieval import EvidenceItemKind

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_CHUNK_ID_PATTERN = r"^chunk:[0-9a-f]{64}$"
_RUN_ID_PATTERN = r"^retrievalrun:[0-9a-f]{64}$"
_PACKET_ID_PATTERN = r"^evidencepacket:[0-9a-f]{64}$"
_ASSERTION_ID_PATTERN = r"^assertion:[0-9a-f]{64}$"
_CITATION_ID_PATTERN = r"^citation:[0-9a-f]{64}$"
_REPORT_ID_PATTERN = r"^report:[0-9a-f]{64}$"
_FINDING_ID_PATTERN = r"^finding:[0-9a-f]{64}$"
_TASK_ID_PATTERN = r"^task:[0-9a-f]{64}$"
_IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_SUBJECT_PATTERN = r"^[a-z0-9][a-z0-9:_./-]{0,127}$"


class SpecialistType(StrEnum):
    DOCUMENT_EVIDENCE = "document_evidence"
    # Remaining registry entries stay blocked until later slices.
    TOKENOMICS = "tokenomics"
    SECURITY = "security"
    GOVERNANCE = "governance"
    TREASURY = "treasury"
    ON_CHAIN = "on_chain"
    MARKET = "market"
    DEVELOPMENT = "development"
    CONTRADICTION = "contradiction"
    SCENARIO = "scenario"


DEVELOPMENT_SPECIALISTS = frozenset({SpecialistType.DOCUMENT_EVIDENCE})


class FindingCompletionStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    CONFLICTED = "conflicted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_APPLICABLE = "not_applicable"
    FAILED = "failed"


class CitationRole(StrEnum):
    DIRECT_SUPPORT = "direct_support"
    CALCULATION_INPUT = "calculation_input"
    METHODOLOGY = "methodology"
    QUALIFICATION = "qualification"
    CONTRADICTION = "contradiction"
    BACKGROUND = "background"


class ReviewAction(StrEnum):
    APPROVE = "approve"
    APPROVE_WITH_QUALIFICATION = "approve_with_qualification"
    EDIT = "edit"
    REQUEST_MORE_EVIDENCE = "request_more_evidence"
    REJECT = "reject"
    MARK_UNRESOLVED = "mark_unresolved"
    SUPERSEDE_PREVIOUS_DECISION = "supersede_previous_decision"


class ReportPublicationOutcome(StrEnum):
    DRAFT = "draft"
    AWAIT_ANALYST_REVIEW = "await_analyst_review"
    REJECTED = "rejected"
    # publish / publish_as_degraded blocked until full gate evidence exists


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


def _canonical_json(payload: object) -> str:
    return dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class SpecialistTask(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    task_id: str = Field(pattern=_TASK_ID_PATTERN)
    specialist_type: SpecialistType
    run_id: str = Field(pattern=_RUN_ID_PATTERN)
    packet_id: str = Field(pattern=_PACKET_ID_PATTERN)
    subquestion: str = Field(min_length=1, max_length=1_000)
    permitted_subjects: tuple[str, ...] = Field(default=(), max_length=32)
    context_budget_tokens: StrictInt = Field(ge=64, le=32_000)
    repair_limit: StrictInt = Field(ge=0, le=2)
    materiality: Literal["low", "medium", "high"] = "medium"

    @model_validator(mode="after")
    def specialist_is_development_allowed(self) -> Self:
        if self.specialist_type not in DEVELOPMENT_SPECIALISTS:
            raise ValueError(
                f"specialist {self.specialist_type} is blocked in the development slice "
                "(document_evidence only)"
            )
        for subject in self.permitted_subjects:
            if not re.fullmatch(_SUBJECT_PATTERN, subject):
                raise ValueError("permitted subject format is invalid")
        if len(set(self.permitted_subjects)) != len(self.permitted_subjects):
            raise ValueError("permitted_subjects must be unique")
        return self


class SpecialistFinding(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    finding_id: str = Field(pattern=_FINDING_ID_PATTERN)
    task_id: str = Field(pattern=_TASK_ID_PATTERN)
    specialist_type: SpecialistType
    answer: str = Field(min_length=1, max_length=4_000)
    supporting_chunk_ids: tuple[str, ...] = Field(default=(), max_length=32)
    contradictory_chunk_ids: tuple[str, ...] = Field(default=(), max_length=32)
    assumptions: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    completion_status: FindingCompletionStatus
    confidence: StrictFloat = Field(ge=0.0, le=1.0)
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="recorded_at")

    @model_validator(mode="after")
    def finding_is_consistent(self) -> Self:
        if self.specialist_type not in DEVELOPMENT_SPECIALISTS:
            raise ValueError("specialist type is blocked in the development slice")
        for chunk_id in (*self.supporting_chunk_ids, *self.contradictory_chunk_ids):
            if not re.fullmatch(_CHUNK_ID_PATTERN, chunk_id):
                raise ValueError("chunk_id format is invalid")
        expected = specialist_finding_id(
            task_id=self.task_id,
            answer=self.answer,
            completion_status=self.completion_status,
            supporting_chunk_ids=self.supporting_chunk_ids,
        )
        if self.finding_id != expected:
            raise ValueError("finding_id does not match deterministic identity")
        if (
            self.completion_status is FindingCompletionStatus.SUPPORTED
            and not self.supporting_chunk_ids
        ):
            raise ValueError("supported findings require supporting evidence")
        return self


class ResearchAssertion(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    assertion_id: str = Field(pattern=_ASSERTION_ID_PATTERN)
    run_id: str = Field(pattern=_RUN_ID_PATTERN)
    finding_id: str = Field(pattern=_FINDING_ID_PATTERN)
    statement: str = Field(min_length=1, max_length=2_000)
    subject_ids: tuple[str, ...] = Field(default=(), max_length=16)
    supporting_chunk_ids: tuple[str, ...] = Field(min_length=1, max_length=32)
    contradictory_chunk_ids: tuple[str, ...] = Field(default=(), max_length=32)
    is_interpretation: bool = False
    confidence: StrictFloat = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def assertion_is_consistent(self) -> Self:
        for chunk_id in (*self.supporting_chunk_ids, *self.contradictory_chunk_ids):
            if not re.fullmatch(_CHUNK_ID_PATTERN, chunk_id):
                raise ValueError("chunk_id format is invalid")
        for subject in self.subject_ids:
            if not re.fullmatch(_SUBJECT_PATTERN, subject):
                raise ValueError("subject_id format is invalid")
        expected = research_assertion_id(
            run_id=self.run_id,
            finding_id=self.finding_id,
            statement=self.statement,
            supporting_chunk_ids=self.supporting_chunk_ids,
        )
        if self.assertion_id != expected:
            raise ValueError("assertion_id does not match deterministic identity")
        return self


class CitationBinding(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    citation_id: str = Field(pattern=_CITATION_ID_PATTERN)
    assertion_id: str = Field(pattern=_ASSERTION_ID_PATTERN)
    chunk_id: str = Field(pattern=_CHUNK_ID_PATTERN)
    role: CitationRole
    excerpt_hash: str = Field(pattern=_SHA256_PATTERN)
    locator: str = Field(min_length=1, max_length=240)
    item_kind: EvidenceItemKind = EvidenceItemKind.SOURCE_CONTENT

    @model_validator(mode="after")
    def citation_rules(self) -> Self:
        if self.item_kind is not EvidenceItemKind.SOURCE_CONTENT:
            raise ValueError("primary citations must bind SOURCE_CONTENT evidence")
        if self.role is CitationRole.CALCULATION_INPUT:
            raise ValueError("calculation citations require Phase 4 calculation plane")
        expected = citation_binding_id(
            assertion_id=self.assertion_id,
            chunk_id=self.chunk_id,
            role=self.role,
            excerpt_hash=self.excerpt_hash,
        )
        if self.citation_id != expected:
            raise ValueError("citation_id does not match deterministic identity")
        return self


class ReportSection(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    section_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    title: str = Field(min_length=1, max_length=120)
    prose: str = Field(min_length=1, max_length=8_000)
    assertion_ids: tuple[str, ...] = Field(min_length=1, max_length=64)


class ReportDraft(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    report_id: str = Field(pattern=_REPORT_ID_PATTERN)
    run_id: str = Field(pattern=_RUN_ID_PATTERN)
    context: ArtifactCommandContext
    title: str = Field(min_length=1, max_length=200)
    sections: tuple[ReportSection, ...] = Field(min_length=1, max_length=32)
    assertions: tuple[ResearchAssertion, ...] = Field(min_length=1, max_length=128)
    citations: tuple[CitationBinding, ...] = Field(min_length=1, max_length=256)
    outcome: ReportPublicationOutcome = ReportPublicationOutcome.DRAFT
    version: StrictInt = Field(ge=1, le=10_000)
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="recorded_at")

    @model_validator(mode="after")
    def report_is_internally_consistent(self) -> Self:
        assertion_ids = {item.assertion_id for item in self.assertions}
        citation_assertions = {item.assertion_id for item in self.citations}
        if not citation_assertions.issubset(assertion_ids):
            raise ValueError("citations must reference report assertions")
        for section in self.sections:
            if not set(section.assertion_ids).issubset(assertion_ids):
                raise ValueError("section assertion_ids must exist on the report")
        # Every assertion must have at least one direct_support citation.
        for assertion in self.assertions:
            supports = [
                citation
                for citation in self.citations
                if citation.assertion_id == assertion.assertion_id
                and citation.role is CitationRole.DIRECT_SUPPORT
            ]
            if not supports:
                raise ValueError("each assertion requires a direct_support citation")
            cited_chunks = {citation.chunk_id for citation in supports}
            if not cited_chunks.intersection(assertion.supporting_chunk_ids):
                raise ValueError("direct_support citation must bind a supporting chunk")
        expected = report_draft_id(
            run_id=self.run_id,
            title=self.title,
            version=self.version,
            assertions=self.assertions,
            citations=self.citations,
        )
        if self.report_id != expected:
            raise ValueError("report_id does not match deterministic identity")
        allowed = {
            ReportPublicationOutcome.DRAFT,
            ReportPublicationOutcome.AWAIT_ANALYST_REVIEW,
            ReportPublicationOutcome.REJECTED,
        }
        if self.outcome not in allowed:
            raise ValueError("publication outcomes beyond draft/review are blocked")
        return self


class ReviewDecision(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    decision_id: UUID
    report_id: str = Field(pattern=_REPORT_ID_PATTERN)
    context: ArtifactCommandContext
    action: ReviewAction
    rationale: str = Field(min_length=1, max_length=1_000)
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def recorded_at_is_utc(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="recorded_at")


def specialist_task_id(*, run_id: str, specialist_type: SpecialistType, subquestion: str) -> str:
    material = f"{run_id}|{specialist_type.value}|{subquestion}"
    return f"task:{sha256(material.encode('utf-8')).hexdigest()}"


def specialist_finding_id(
    *,
    task_id: str,
    answer: str,
    completion_status: FindingCompletionStatus,
    supporting_chunk_ids: tuple[str, ...],
) -> str:
    body = {
        "answer": answer,
        "completion_status": completion_status.value,
        "supporting_chunk_ids": list(supporting_chunk_ids),
        "task_id": task_id,
    }
    return f"finding:{sha256(_canonical_json(body).encode('utf-8')).hexdigest()}"


def research_assertion_id(
    *,
    run_id: str,
    finding_id: str,
    statement: str,
    supporting_chunk_ids: tuple[str, ...],
) -> str:
    body = {
        "finding_id": finding_id,
        "run_id": run_id,
        "statement": statement,
        "supporting_chunk_ids": list(supporting_chunk_ids),
    }
    return f"assertion:{sha256(_canonical_json(body).encode('utf-8')).hexdigest()}"


def citation_binding_id(
    *,
    assertion_id: str,
    chunk_id: str,
    role: CitationRole,
    excerpt_hash: str,
) -> str:
    material = f"{assertion_id}|{chunk_id}|{role.value}|{excerpt_hash}"
    return f"citation:{sha256(material.encode('utf-8')).hexdigest()}"


def report_draft_id(
    *,
    run_id: str,
    title: str,
    version: int,
    assertions: tuple[ResearchAssertion, ...],
    citations: tuple[CitationBinding, ...],
) -> str:
    body = {
        "assertions": [item.assertion_id for item in assertions],
        "citations": [item.citation_id for item in citations],
        "run_id": run_id,
        "title": title,
        "version": version,
    }
    return f"report:{sha256(_canonical_json(body).encode('utf-8')).hexdigest()}"
