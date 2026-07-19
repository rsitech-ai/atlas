"""Strict monitoring and comparison contracts for Phase 5 (section 24 development slice)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from json import dumps
from typing import Literal, Self

from pydantic import Field, StrictInt, field_validator, model_validator

from rsi_atlas_contracts.artifact import ArtifactCommandContext
from rsi_atlas_contracts.document_parsing import DocumentContractModel

_SHA256_PATTERN = r"^[0-9a-f]{64}$"
_RULE_ID_PATTERN = r"^rule:[a-z][a-z0-9_]{0,63}$"
_ALERT_ID_PATTERN = r"^alert:[0-9a-f]{64}$"
_EVENT_ID_PATTERN = r"^alertevent:[0-9a-f]{64}$"
_INVALIDATION_ID_PATTERN = r"^invalidation:[0-9a-f]{64}$"
_LAUNCH_ID_PATTERN = r"^researchlaunch:[0-9a-f]{64}$"
_MATRIX_ID_PATTERN = r"^comparison:[0-9a-f]{64}$"
_TIMELINE_ID_PATTERN = r"^timeline:[0-9a-f]{64}$"
_OBSERVATION_ID_PATTERN = r"^observation:[0-9a-f]{64}$"
_ENVELOPE_ID_PATTERN = r"^envelope:[0-9a-f]{64}$"
_REPORT_ID_PATTERN = r"^report:[0-9a-f]{64}$"
_ASSERTION_ID_PATTERN = r"^assertion:[0-9a-f]{64}$"
_SUBJECT_PATTERN = r"^[a-z0-9][a-z0-9:_./-]{0,127}$"
_FIXED_DECIMAL_PATTERN = r"^-?(?:0|[1-9][0-9]{0,38})(?:\.[0-9]{1,18})?$"
_IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"


def _require_utc(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be timezone-aware UTC")
    return value


def _canonical_json(payload: object) -> str:
    return dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class MonitoringRuleType(StrEnum):
    THRESHOLD = "threshold"
    RATE_OF_CHANGE = "rate_of_change"
    STATE_TRANSITION = "state_transition"
    QUALITY_TRANSITION = "quality_transition"
    # Remaining roster stays blocked until later slices.
    ROLLING_ANOMALY = "rolling_anomaly"
    STRUCTURAL_BREAK = "structural_break"
    SEQUENCE_EVENT = "sequence_event"
    DOCUMENT_DIFF = "document_diff"
    SCHEMA_DIFF = "schema_diff"
    CONTRACT_PROGRAM_DIFF = "contract_program_diff"
    CROSS_SOURCE_DISAGREEMENT = "cross_source_disagreement"
    COMPOSITE = "composite"
    SCHEDULED_REEVALUATION = "scheduled_reevaluation"


DEVELOPMENT_RULE_TYPES = frozenset(
    {
        MonitoringRuleType.THRESHOLD,
        MonitoringRuleType.RATE_OF_CHANGE,
        MonitoringRuleType.STATE_TRANSITION,
        MonitoringRuleType.QUALITY_TRANSITION,
    }
)

BLOCKED_RULE_TYPES = frozenset(MonitoringRuleType) - DEVELOPMENT_RULE_TYPES


class ChangeKind(StrEnum):
    THRESHOLD_BREACH = "threshold_breach"
    RATE_OF_CHANGE = "rate_of_change"
    FINALITY_TRANSITION = "finality_transition"
    QUALITY_TRANSITION = "quality_transition"
    ORPHANED = "orphaned"
    QUARANTINED = "quarantined"
    NO_MATERIAL_CHANGE = "no_material_change"


class MaterialityOutcome(StrEnum):
    RECORD_ONLY = "record_only"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    REQUIRES_MORE_EVIDENCE = "requires_more_evidence"


class AlertLifecycle(StrEnum):
    DETECTED = "detected"
    TRIAGING = "triaging"
    VALIDATED = "validated"
    AWAITING_REVIEW = "awaiting_review"
    PUBLISHED = "published"
    ACKNOWLEDGED = "acknowledged"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"
    SUPERSEDED = "superseded"


ALERT_LIFECYCLE_TRANSITIONS: dict[AlertLifecycle, frozenset[AlertLifecycle]] = {
    AlertLifecycle.DETECTED: frozenset(
        {
            AlertLifecycle.TRIAGING,
            AlertLifecycle.VALIDATED,
            AlertLifecycle.DISMISSED,
            AlertLifecycle.SUPERSEDED,
        }
    ),
    AlertLifecycle.TRIAGING: frozenset(
        {
            AlertLifecycle.VALIDATED,
            AlertLifecycle.AWAITING_REVIEW,
            AlertLifecycle.DISMISSED,
            AlertLifecycle.SUPERSEDED,
        }
    ),
    AlertLifecycle.VALIDATED: frozenset(
        {
            AlertLifecycle.AWAITING_REVIEW,
            AlertLifecycle.PUBLISHED,
            AlertLifecycle.DISMISSED,
            AlertLifecycle.SUPERSEDED,
        }
    ),
    AlertLifecycle.AWAITING_REVIEW: frozenset(
        {
            AlertLifecycle.PUBLISHED,
            AlertLifecycle.ACKNOWLEDGED,
            AlertLifecycle.DISMISSED,
            AlertLifecycle.SUPERSEDED,
        }
    ),
    AlertLifecycle.PUBLISHED: frozenset(
        {
            AlertLifecycle.ACKNOWLEDGED,
            AlertLifecycle.INVESTIGATING,
            AlertLifecycle.RESOLVED,
            AlertLifecycle.DISMISSED,
            AlertLifecycle.SUPERSEDED,
        }
    ),
    AlertLifecycle.ACKNOWLEDGED: frozenset(
        {
            AlertLifecycle.INVESTIGATING,
            AlertLifecycle.RESOLVED,
            AlertLifecycle.DISMISSED,
            AlertLifecycle.SUPERSEDED,
        }
    ),
    AlertLifecycle.INVESTIGATING: frozenset(
        {
            AlertLifecycle.RESOLVED,
            AlertLifecycle.DISMISSED,
            AlertLifecycle.SUPERSEDED,
        }
    ),
    AlertLifecycle.RESOLVED: frozenset({AlertLifecycle.SUPERSEDED}),
    AlertLifecycle.DISMISSED: frozenset({AlertLifecycle.SUPERSEDED}),
    AlertLifecycle.SUPERSEDED: frozenset(),
}


class InvalidationReason(StrEnum):
    ORPHANED_OBSERVATION = "orphaned_observation"
    QUARANTINED_INPUT = "quarantined_input"
    SUPERSEDED_FEATURE = "superseded_feature"
    MATERIAL_CHANGE = "material_change"


class TimelineEventKind(StrEnum):
    OBSERVATION = "observation"
    ALERT = "alert"
    INVALIDATION = "invalidation"
    RESEARCH_LAUNCH = "research_launch"


class SemanticTriageStatus(StrEnum):
    BLOCKED_SEMANTIC_TRIAGE = "blocked_semantic_triage"


class ComparisonAxis(StrEnum):
    FINALITY = "finality"
    QUALITY = "quality"
    MARKET_PRICE = "market_price"
    GOVERNANCE_STATE = "governance_state"
    GITHUB_RELEASE = "github_release"
    SOURCE_FAMILY = "source_family"


class MonitoringRule(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    rule_id: str = Field(pattern=_RULE_ID_PATTERN)
    rule_type: MonitoringRuleType
    subject_id: str = Field(pattern=_SUBJECT_PATTERN)
    metric_name: str = Field(pattern=_IDENTIFIER_PATTERN)
    threshold: str | None = Field(default=None, pattern=_FIXED_DECIMAL_PATTERN)
    rate_window_seconds: StrictInt | None = Field(default=None, ge=1, le=86_400)
    severity_floor: MaterialityOutcome
    dedup_window_seconds: StrictInt = Field(default=3600, ge=1, le=604_800)
    enabled: bool = True

    @model_validator(mode="after")
    def development_rule_types_only(self) -> Self:
        if self.rule_type in BLOCKED_RULE_TYPES:
            raise ValueError(f"rule_type {self.rule_type.value} remains blocked without governance")
        if self.rule_type is MonitoringRuleType.THRESHOLD and self.threshold is None:
            raise ValueError("threshold rules require threshold")
        if self.rule_type is MonitoringRuleType.RATE_OF_CHANGE and self.rate_window_seconds is None:
            raise ValueError("rate_of_change rules require rate_window_seconds")
        if self.severity_floor is MaterialityOutcome.RECORD_ONLY:
            raise ValueError("severity_floor cannot be record_only")
        return self


class DeterministicMeasurement(DocumentContractModel):
    name: str = Field(pattern=_IDENTIFIER_PATTERN)
    previous_value: str = Field(min_length=1, max_length=128)
    current_value: str = Field(min_length=1, max_length=128)
    unit: str = Field(min_length=1, max_length=32)
    delta: str | None = Field(default=None, pattern=_FIXED_DECIMAL_PATTERN)


class ChangeDetection(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    context: ArtifactCommandContext
    change_kind: ChangeKind
    subject_id: str = Field(pattern=_SUBJECT_PATTERN)
    previous_observation_id: str | None = Field(default=None, pattern=_OBSERVATION_ID_PATTERN)
    current_observation_id: str = Field(pattern=_OBSERVATION_ID_PATTERN)
    previous_envelope_id: str | None = Field(default=None, pattern=_ENVELOPE_ID_PATTERN)
    current_envelope_id: str = Field(pattern=_ENVELOPE_ID_PATTERN)
    event_time: datetime
    detected_at: datetime
    measurements: tuple[DeterministicMeasurement, ...] = Field(min_length=1, max_length=32)
    confidence: str = Field(pattern=_FIXED_DECIMAL_PATTERN)

    @field_validator("event_time", "detected_at")
    @classmethod
    def utc_times(cls, value: datetime, info: object) -> datetime:
        field_name = getattr(info, "field_name", "timestamp")
        return _require_utc(value, field_name=str(field_name))

    @model_validator(mode="after")
    def confidence_bounds(self) -> Self:
        confidence = Decimal(self.confidence)
        if confidence < 0 or confidence > 1:
            raise ValueError("confidence must be in [0, 1]")
        return self


class MaterialityDecision(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    outcome: MaterialityOutcome
    rule_id: str = Field(pattern=_RULE_ID_PATTERN)
    change_kind: ChangeKind
    magnitude: str = Field(pattern=_FIXED_DECIMAL_PATTERN)
    confidence: str = Field(pattern=_FIXED_DECIMAL_PATTERN)
    rationale: str = Field(min_length=1, max_length=512)
    requires_semantic_triage: Literal[False] = False

    @model_validator(mode="after")
    def deterministic_only(self) -> Self:
        if self.requires_semantic_triage:
            raise ValueError("materiality decisions cannot require semantic triage in-slice")
        confidence = Decimal(self.confidence)
        if confidence < 0 or confidence > 1:
            raise ValueError("confidence must be in [0, 1]")
        return self


def alert_dedup_key(
    *,
    subject_id: str,
    rule_id: str,
    underlying_event_id: str,
    state_transition: str,
    window_bucket: int,
) -> str:
    payload = {
        "rule_id": rule_id,
        "state_transition": state_transition,
        "subject_id": subject_id,
        "underlying_event_id": underlying_event_id,
        "window_bucket": window_bucket,
    }
    return sha256(_canonical_json(payload).encode()).hexdigest()


def alert_id(*, dedup_key: str) -> str:
    if not re.fullmatch(_SHA256_PATTERN, dedup_key):
        raise ValueError("dedup_key must be sha256 hex")
    return f"alert:{dedup_key}"


class Alert(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    context: ArtifactCommandContext
    alert_id: str = Field(pattern=_ALERT_ID_PATTERN)
    dedup_key: str = Field(pattern=_SHA256_PATTERN)
    rule_id: str = Field(pattern=_RULE_ID_PATTERN)
    subject_id: str = Field(pattern=_SUBJECT_PATTERN)
    severity: MaterialityOutcome
    status: AlertLifecycle
    detected_at: datetime
    event_time: datetime
    previous_observation_id: str | None = Field(default=None, pattern=_OBSERVATION_ID_PATTERN)
    current_observation_id: str = Field(pattern=_OBSERVATION_ID_PATTERN)
    previous_envelope_id: str | None = Field(default=None, pattern=_ENVELOPE_ID_PATTERN)
    current_envelope_id: str = Field(pattern=_ENVELOPE_ID_PATTERN)
    change_summary: str = Field(min_length=1, max_length=512)
    measurements: tuple[DeterministicMeasurement, ...] = Field(min_length=1, max_length=32)
    affected_report_ids: tuple[str, ...] = Field(default=(), max_length=64)
    affected_assertion_ids: tuple[str, ...] = Field(default=(), max_length=128)
    confidence: str = Field(pattern=_FIXED_DECIMAL_PATTERN)
    missing_evidence: tuple[str, ...] = Field(default=(), max_length=32)

    @field_validator("detected_at", "event_time")
    @classmethod
    def utc_alert_times(cls, value: datetime, info: object) -> datetime:
        field_name = getattr(info, "field_name", "timestamp")
        return _require_utc(value, field_name=str(field_name))

    @model_validator(mode="after")
    def identity_and_links(self) -> Self:
        if self.alert_id != alert_id(dedup_key=self.dedup_key):
            raise ValueError("alert_id does not match dedup_key")
        if self.severity is MaterialityOutcome.RECORD_ONLY:
            raise ValueError("alerts cannot have record_only severity")
        for report_id in self.affected_report_ids:
            if not re.fullmatch(_REPORT_ID_PATTERN, report_id):
                raise ValueError(f"invalid report_id: {report_id}")
        for assertion_id in self.affected_assertion_ids:
            if not re.fullmatch(_ASSERTION_ID_PATTERN, assertion_id):
                raise ValueError(f"invalid assertion_id: {assertion_id}")
        return self


class AlertEvent(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    context: ArtifactCommandContext
    event_id: str = Field(pattern=_EVENT_ID_PATTERN)
    alert_id: str = Field(pattern=_ALERT_ID_PATTERN)
    from_status: AlertLifecycle | None
    to_status: AlertLifecycle
    recorded_at: datetime
    note: str = Field(default="", max_length=512)

    @field_validator("recorded_at")
    @classmethod
    def utc_recorded(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="recorded_at")

    @model_validator(mode="after")
    def legal_transition(self) -> Self:
        if self.from_status is None:
            if self.to_status is not AlertLifecycle.DETECTED:
                raise ValueError("initial alert event must transition to detected")
            return self
        allowed = ALERT_LIFECYCLE_TRANSITIONS[self.from_status]
        if self.to_status not in allowed:
            raise ValueError(
                f"illegal alert lifecycle transition {self.from_status.value} -> "
                f"{self.to_status.value}"
            )
        return self


def alert_event_id(
    *,
    alert_id_value: str,
    to_status: AlertLifecycle,
    recorded_at: datetime,
) -> str:
    payload = {
        "alert_id": alert_id_value,
        "recorded_at": recorded_at.isoformat().replace("+00:00", "Z"),
        "to_status": to_status.value,
    }
    return f"alertevent:{sha256(_canonical_json(payload).encode()).hexdigest()}"


class ResearchInvalidation(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    context: ArtifactCommandContext
    invalidation_id: str = Field(pattern=_INVALIDATION_ID_PATTERN)
    reason: InvalidationReason
    subject_id: str = Field(pattern=_SUBJECT_PATTERN)
    observation_id: str | None = Field(default=None, pattern=_OBSERVATION_ID_PATTERN)
    envelope_id: str | None = Field(default=None, pattern=_ENVELOPE_ID_PATTERN)
    alert_id: str | None = Field(default=None, pattern=_ALERT_ID_PATTERN)
    affected_report_ids: tuple[str, ...] = Field(default=(), max_length=64)
    affected_assertion_ids: tuple[str, ...] = Field(default=(), max_length=128)
    recorded_at: datetime
    summary: str = Field(min_length=1, max_length=512)

    @field_validator("recorded_at")
    @classmethod
    def utc_recorded(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="recorded_at")

    @model_validator(mode="after")
    def evidence_or_reports(self) -> Self:
        if self.observation_id is None and self.envelope_id is None:
            raise ValueError("invalidation requires observation_id or envelope_id")
        for report_id in self.affected_report_ids:
            if not re.fullmatch(_REPORT_ID_PATTERN, report_id):
                raise ValueError(f"invalid report_id: {report_id}")
        return self


def research_invalidation_id(
    *,
    reason: InvalidationReason,
    subject_id: str,
    observation_id: str | None,
    envelope_id: str | None,
    recorded_at: datetime,
) -> str:
    payload = {
        "envelope_id": envelope_id,
        "observation_id": observation_id,
        "reason": reason.value,
        "recorded_at": recorded_at.isoformat().replace("+00:00", "Z"),
        "subject_id": subject_id,
    }
    return f"invalidation:{sha256(_canonical_json(payload).encode()).hexdigest()}"


class TargetedResearchLaunch(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    context: ArtifactCommandContext
    launch_id: str = Field(pattern=_LAUNCH_ID_PATTERN)
    alert_id: str = Field(pattern=_ALERT_ID_PATTERN)
    subject_id: str = Field(pattern=_SUBJECT_PATTERN)
    plan_hash: str = Field(pattern=_SHA256_PATTERN)
    status: Literal["recorded_stub", "queued_workflow"] = "recorded_stub"
    recorded_at: datetime
    note: str = Field(
        default="targeted research launch recorded; LangGraph execution deferred",
        min_length=1,
        max_length=256,
    )

    @field_validator("recorded_at")
    @classmethod
    def utc_recorded(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="recorded_at")


def targeted_research_launch_id(*, alert_id_value: str, plan_hash: str) -> str:
    payload = {"alert_id": alert_id_value, "plan_hash": plan_hash}
    return f"researchlaunch:{sha256(_canonical_json(payload).encode()).hexdigest()}"


class ComparisonCell(DocumentContractModel):
    subject_id: str = Field(pattern=_SUBJECT_PATTERN)
    axis: ComparisonAxis
    value: str = Field(min_length=1, max_length=256)
    observation_id: str = Field(pattern=_OBSERVATION_ID_PATTERN)
    envelope_id: str = Field(pattern=_ENVELOPE_ID_PATTERN)
    source_family: str = Field(pattern=_IDENTIFIER_PATTERN)
    as_of: datetime

    @field_validator("as_of")
    @classmethod
    def utc_as_of(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="as_of")


class ComparisonMatrix(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    context: ArtifactCommandContext
    matrix_id: str = Field(pattern=_MATRIX_ID_PATTERN)
    axes: tuple[ComparisonAxis, ...] = Field(min_length=1, max_length=8)
    subjects: tuple[str, ...] = Field(min_length=1, max_length=32)
    cells: tuple[ComparisonCell, ...] = Field(min_length=1, max_length=256)
    as_of: datetime

    @field_validator("as_of")
    @classmethod
    def utc_as_of(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="as_of")

    @model_validator(mode="after")
    def cells_match_subjects(self) -> Self:
        subject_set = set(self.subjects)
        for subject in self.subjects:
            if not re.fullmatch(_SUBJECT_PATTERN, subject):
                raise ValueError(f"invalid subject_id: {subject}")
        for cell in self.cells:
            if cell.subject_id not in subject_set:
                raise ValueError("comparison cell subject not in matrix subjects")
            if cell.axis not in self.axes:
                raise ValueError("comparison cell axis not in matrix axes")
        return self


def comparison_matrix_id(
    *,
    subjects: tuple[str, ...],
    axes: tuple[ComparisonAxis, ...],
    as_of: datetime,
) -> str:
    payload = {
        "as_of": as_of.isoformat().replace("+00:00", "Z"),
        "axes": [axis.value for axis in axes],
        "subjects": list(subjects),
    }
    return f"comparison:{sha256(_canonical_json(payload).encode()).hexdigest()}"


class TimelineEvent(DocumentContractModel):
    event_kind: TimelineEventKind
    subject_id: str = Field(pattern=_SUBJECT_PATTERN)
    event_time: datetime
    observation_id: str | None = Field(default=None, pattern=_OBSERVATION_ID_PATTERN)
    envelope_id: str | None = Field(default=None, pattern=_ENVELOPE_ID_PATTERN)
    alert_id: str | None = Field(default=None, pattern=_ALERT_ID_PATTERN)
    summary: str = Field(min_length=1, max_length=512)
    source_family: str | None = Field(default=None, pattern=_IDENTIFIER_PATTERN)

    @field_validator("event_time")
    @classmethod
    def utc_event_time(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="event_time")

    @model_validator(mode="after")
    def evidence_links(self) -> Self:
        if self.event_kind is TimelineEventKind.OBSERVATION and (
            self.observation_id is None or self.envelope_id is None
        ):
            raise ValueError("observation timeline events require observation and envelope ids")
        if self.event_kind is TimelineEventKind.ALERT and self.alert_id is None:
            raise ValueError("alert timeline events require alert_id")
        return self


class CrossChainTimeline(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    context: ArtifactCommandContext
    timeline_id: str = Field(pattern=_TIMELINE_ID_PATTERN)
    subjects: tuple[str, ...] = Field(min_length=1, max_length=32)
    events: tuple[TimelineEvent, ...] = Field(min_length=1, max_length=512)
    as_of: datetime

    @field_validator("as_of")
    @classmethod
    def utc_as_of(cls, value: datetime) -> datetime:
        return _require_utc(value, field_name="as_of")


def cross_chain_timeline_id(*, subjects: tuple[str, ...], as_of: datetime) -> str:
    payload = {
        "as_of": as_of.isoformat().replace("+00:00", "Z"),
        "subjects": list(subjects),
    }
    return f"timeline:{sha256(_canonical_json(payload).encode()).hexdigest()}"


class SemanticTriageRequest(DocumentContractModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    alert_id: str = Field(pattern=_ALERT_ID_PATTERN)
    change_summary: str = Field(min_length=1, max_length=512)


class SemanticTriageGate(DocumentContractModel):
    status: SemanticTriageStatus = SemanticTriageStatus.BLOCKED_SEMANTIC_TRIAGE
    reason: str = Field(
        default="calibrated semantic triage models are not promoted in this development slice",
        min_length=1,
        max_length=256,
    )

    @model_validator(mode="after")
    def always_blocked(self) -> Self:
        if self.status is not SemanticTriageStatus.BLOCKED_SEMANTIC_TRIAGE:
            raise ValueError("semantic triage remains blocked_semantic_triage")
        return self
