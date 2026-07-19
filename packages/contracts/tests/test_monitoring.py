"""Strict Phase 5 monitoring and comparison contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError
from rsi_atlas_contracts import (
    ALERT_LIFECYCLE_TRANSITIONS,
    BLOCKED_RULE_TYPES,
    DEVELOPMENT_RULE_TYPES,
    Alert,
    AlertEvent,
    AlertLifecycle,
    ArtifactCommandContext,
    ChangeDetection,
    ChangeKind,
    ComparisonAxis,
    ComparisonCell,
    ComparisonMatrix,
    CrossChainTimeline,
    DeterministicMeasurement,
    InvalidationReason,
    MaterialityDecision,
    MaterialityOutcome,
    MonitoringRule,
    MonitoringRuleType,
    ResearchInvalidation,
    SemanticTriageGate,
    SemanticTriageStatus,
    TargetedResearchLaunch,
    TimelineEvent,
    TimelineEventKind,
    alert_dedup_key,
    alert_event_id,
    alert_id,
    comparison_matrix_id,
    cross_chain_timeline_id,
    research_invalidation_id,
    targeted_research_launch_id,
)

TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000002")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000000003")
TRACE_ID = UUID("00000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
OBS_PREV = "observation:" + ("a" * 64)
OBS_CUR = "observation:" + ("b" * 64)
ENV_PREV = "envelope:" + ("c" * 64)
ENV_CUR = "envelope:" + ("d" * 64)
REPORT_ID = "report:" + ("e" * 64)


def _context() -> ArtifactCommandContext:
    return ArtifactCommandContext(
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        trace_id=TRACE_ID,
    )


def _measurement() -> DeterministicMeasurement:
    return DeterministicMeasurement(
        name="price",
        previous_value="100.0",
        current_value="120.0",
        unit="usd",
        delta="20.0",
    )


def test_blocked_rule_types_rejected() -> None:
    assert MonitoringRuleType.ROLLING_ANOMALY in BLOCKED_RULE_TYPES
    with pytest.raises(ValidationError, match="blocked"):
        MonitoringRule(
            rule_id="rule:anomaly",
            rule_type=MonitoringRuleType.ROLLING_ANOMALY,
            subject_id="btc:mainnet",
            metric_name="height",
            severity_floor=MaterialityOutcome.HIGH,
        )


def test_threshold_rule_requires_threshold() -> None:
    assert MonitoringRuleType.THRESHOLD in DEVELOPMENT_RULE_TYPES
    with pytest.raises(ValidationError, match="threshold"):
        MonitoringRule(
            rule_id="rule:price_threshold",
            rule_type=MonitoringRuleType.THRESHOLD,
            subject_id="market:btc_usd",
            metric_name="last_price",
            severity_floor=MaterialityOutcome.MEDIUM,
        )
    rule = MonitoringRule(
        rule_id="rule:price_threshold",
        rule_type=MonitoringRuleType.THRESHOLD,
        subject_id="market:btc_usd",
        metric_name="last_price",
        threshold="100000.0",
        severity_floor=MaterialityOutcome.MEDIUM,
    )
    assert rule.threshold == "100000.0"


def test_change_detection_requires_utc_and_confidence_bounds() -> None:
    with pytest.raises(ValidationError, match="UTC"):
        ChangeDetection(
            context=_context(),
            change_kind=ChangeKind.RATE_OF_CHANGE,
            subject_id="market:btc_usd",
            current_observation_id=OBS_CUR,
            current_envelope_id=ENV_CUR,
            event_time=datetime(2026, 7, 19, 12, 0),
            detected_at=NOW,
            measurements=(_measurement(),),
            confidence="0.9",
        )
    with pytest.raises(ValidationError, match="confidence"):
        ChangeDetection(
            context=_context(),
            change_kind=ChangeKind.RATE_OF_CHANGE,
            subject_id="market:btc_usd",
            current_observation_id=OBS_CUR,
            current_envelope_id=ENV_CUR,
            event_time=NOW,
            detected_at=NOW,
            measurements=(_measurement(),),
            confidence="1.5",
        )


def test_materiality_forbids_semantic_triage_flag() -> None:
    decision = MaterialityDecision(
        outcome=MaterialityOutcome.HIGH,
        rule_id="rule:price_threshold",
        change_kind=ChangeKind.THRESHOLD_BREACH,
        magnitude="0.2",
        confidence="0.95",
        rationale="price exceeded threshold by 20%",
    )
    assert decision.requires_semantic_triage is False


def test_alert_dedup_and_identity() -> None:
    key = alert_dedup_key(
        subject_id="market:btc_usd",
        rule_id="rule:price_threshold",
        underlying_event_id=OBS_CUR,
        state_transition="100->120",
        window_bucket=1,
    )
    assert len(key) == 64
    assert alert_id(dedup_key=key) == f"alert:{key}"
    alert = Alert(
        context=_context(),
        alert_id=alert_id(dedup_key=key),
        dedup_key=key,
        rule_id="rule:price_threshold",
        subject_id="market:btc_usd",
        severity=MaterialityOutcome.HIGH,
        status=AlertLifecycle.DETECTED,
        detected_at=NOW,
        event_time=NOW,
        previous_observation_id=OBS_PREV,
        current_observation_id=OBS_CUR,
        previous_envelope_id=ENV_PREV,
        current_envelope_id=ENV_CUR,
        change_summary="price rose 20%",
        measurements=(_measurement(),),
        affected_report_ids=(REPORT_ID,),
        confidence="0.9",
    )
    assert alert.current_envelope_id == ENV_CUR
    with pytest.raises(ValidationError, match="record_only"):
        Alert(
            context=_context(),
            alert_id=alert_id(dedup_key=key),
            dedup_key=key,
            rule_id="rule:price_threshold",
            subject_id="market:btc_usd",
            severity=MaterialityOutcome.RECORD_ONLY,
            status=AlertLifecycle.DETECTED,
            detected_at=NOW,
            event_time=NOW,
            current_observation_id=OBS_CUR,
            current_envelope_id=ENV_CUR,
            change_summary="noise",
            measurements=(_measurement(),),
            confidence="0.1",
        )


def test_alert_event_rejects_illegal_transition() -> None:
    key = alert_dedup_key(
        subject_id="market:btc_usd",
        rule_id="rule:price_threshold",
        underlying_event_id=OBS_CUR,
        state_transition="100->120",
        window_bucket=1,
    )
    aid = alert_id(dedup_key=key)
    event = AlertEvent(
        context=_context(),
        event_id=alert_event_id(
            alert_id_value=aid,
            to_status=AlertLifecycle.DETECTED,
            recorded_at=NOW,
        ),
        alert_id=aid,
        from_status=None,
        to_status=AlertLifecycle.DETECTED,
        recorded_at=NOW,
    )
    assert event.to_status is AlertLifecycle.DETECTED
    assert AlertLifecycle.PUBLISHED in ALERT_LIFECYCLE_TRANSITIONS[AlertLifecycle.VALIDATED]
    with pytest.raises(ValidationError, match="illegal"):
        AlertEvent(
            context=_context(),
            event_id=alert_event_id(
                alert_id_value=aid,
                to_status=AlertLifecycle.RESOLVED,
                recorded_at=NOW,
            ),
            alert_id=aid,
            from_status=AlertLifecycle.DETECTED,
            to_status=AlertLifecycle.RESOLVED,
            recorded_at=NOW,
        )


def test_research_invalidation_requires_evidence_link() -> None:
    with pytest.raises(ValidationError, match="observation_id or envelope_id"):
        ResearchInvalidation(
            context=_context(),
            invalidation_id=research_invalidation_id(
                reason=InvalidationReason.ORPHANED_OBSERVATION,
                subject_id="btc:mainnet",
                observation_id=None,
                envelope_id=None,
                recorded_at=NOW,
            ),
            reason=InvalidationReason.ORPHANED_OBSERVATION,
            subject_id="btc:mainnet",
            recorded_at=NOW,
            summary="orphaned",
        )
    record = ResearchInvalidation(
        context=_context(),
        invalidation_id=research_invalidation_id(
            reason=InvalidationReason.ORPHANED_OBSERVATION,
            subject_id="btc:mainnet",
            observation_id=OBS_CUR,
            envelope_id=ENV_CUR,
            recorded_at=NOW,
        ),
        reason=InvalidationReason.ORPHANED_OBSERVATION,
        subject_id="btc:mainnet",
        observation_id=OBS_CUR,
        envelope_id=ENV_CUR,
        affected_report_ids=(REPORT_ID,),
        recorded_at=NOW,
        summary="observation orphaned by reorg stub",
    )
    assert REPORT_ID in record.affected_report_ids


def test_targeted_research_launch_is_stub_only() -> None:
    key = alert_dedup_key(
        subject_id="market:btc_usd",
        rule_id="rule:price_threshold",
        underlying_event_id=OBS_CUR,
        state_transition="100->120",
        window_bucket=1,
    )
    aid = alert_id(dedup_key=key)
    plan_hash = "f" * 64
    launch = TargetedResearchLaunch(
        context=_context(),
        launch_id=targeted_research_launch_id(alert_id_value=aid, plan_hash=plan_hash),
        alert_id=aid,
        subject_id="market:btc_usd",
        plan_hash=plan_hash,
        recorded_at=NOW,
    )
    assert launch.status == "recorded_stub"


def test_comparison_matrix_and_timeline_link_evidence() -> None:
    axes = (ComparisonAxis.QUALITY, ComparisonAxis.SOURCE_FAMILY)
    subjects = ("btc:mainnet", "evm:1")
    cell = ComparisonCell(
        subject_id="btc:mainnet",
        axis=ComparisonAxis.QUALITY,
        value="accepted",
        observation_id=OBS_CUR,
        envelope_id=ENV_CUR,
        source_family="bitcoin",
        as_of=NOW,
    )
    matrix = ComparisonMatrix(
        context=_context(),
        matrix_id=comparison_matrix_id(subjects=subjects, axes=axes, as_of=NOW),
        axes=axes,
        subjects=subjects,
        cells=(cell,),
        as_of=NOW,
    )
    assert matrix.cells[0].envelope_id == ENV_CUR
    timeline = CrossChainTimeline(
        context=_context(),
        timeline_id=cross_chain_timeline_id(subjects=subjects, as_of=NOW),
        subjects=subjects,
        events=(
            TimelineEvent(
                event_kind=TimelineEventKind.OBSERVATION,
                subject_id="btc:mainnet",
                event_time=NOW,
                observation_id=OBS_CUR,
                envelope_id=ENV_CUR,
                summary="bitcoin block observed",
                source_family="bitcoin",
            ),
        ),
        as_of=NOW,
    )
    assert timeline.events[0].observation_id == OBS_CUR
    with pytest.raises(ValidationError, match="observation and envelope"):
        TimelineEvent(
            event_kind=TimelineEventKind.OBSERVATION,
            subject_id="btc:mainnet",
            event_time=NOW,
            summary="missing ids",
        )


def test_semantic_triage_gate_always_blocked() -> None:
    gate = SemanticTriageGate()
    assert gate.status is SemanticTriageStatus.BLOCKED_SEMANTIC_TRIAGE
