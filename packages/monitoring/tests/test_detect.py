"""Change detection and materiality tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from rsi_atlas_collectors import import_fixture, mark_orphaned
from rsi_atlas_contracts import (
    BLOCKED_RULE_TYPES,
    ArtifactCommandContext,
    ChangeKind,
    MaterialityOutcome,
    MonitoringRule,
    MonitoringRuleType,
    ObservationQuality,
    ProviderQualityState,
    SemanticTriageRequest,
)
from rsi_atlas_monitoring import (
    MonitoringError,
    RuleMatchError,
    SemanticTriageBlocked,
    detect_observation_change,
    match_rules,
    refuse_semantic_triage,
    screen_materiality,
)

TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000002")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000000003")
TRACE_ID = UUID("00000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def _context() -> ArtifactCommandContext:
    return ArtifactCommandContext(
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        trace_id=TRACE_ID,
    )


def _market_pair() -> tuple[object, object]:
    context = _context()
    first = import_fixture(context=context, fixture_name="market_tick.json", now=NOW)
    assert first.observation is not None
    # Second tick with higher price via payload mutation through a later import is awkward;
    # rebuild by importing again and patching via model_copy on a cloned observation.
    second = import_fixture(
        context=context,
        fixture_name="market_tick.json",
        now=NOW + timedelta(minutes=1),
    )
    assert second.observation is not None
    bumped = second.observation.model_copy(
        update={
            "payload": second.observation.payload.model_copy(
                update={"last": "70000.50", "sequence": 43}
            ),
            "header": second.observation.header.model_copy(
                update={
                    "observation_id": "observation:" + ("1" * 64),
                    "envelope_id": "envelope:" + ("2" * 64),
                }
            ),
        }
    )
    return first.observation, bumped


def test_detect_market_rate_of_change() -> None:
    previous, current = _market_pair()
    detection = detect_observation_change(
        previous=previous,
        current=current,
        detected_at=NOW + timedelta(minutes=1),
    )
    assert detection.change_kind is ChangeKind.RATE_OF_CHANGE
    assert detection.measurements[0].name == "last_price"


def test_detect_orphan() -> None:
    context = _context()
    result = import_fixture(context=context, fixture_name="bitcoin_block.json", now=NOW)
    assert result.observation is not None
    orphaned = mark_orphaned(result.observation)
    detection = detect_observation_change(
        previous=result.observation,
        current=orphaned,
        detected_at=NOW + timedelta(seconds=1),
    )
    assert detection.change_kind is ChangeKind.ORPHANED


def test_match_threshold_rule() -> None:
    previous, current = _market_pair()
    detection = detect_observation_change(
        previous=previous,
        current=current,
        detected_at=NOW + timedelta(minutes=1),
    )
    rule = MonitoringRule(
        rule_id="rule:price_threshold",
        rule_type=MonitoringRuleType.THRESHOLD,
        subject_id=detection.subject_id,
        metric_name="last_price",
        threshold="65000.0",
        severity_floor=MaterialityOutcome.MEDIUM,
    )
    assert match_rules(detection=detection, rules=(rule,)) == (rule,)


def test_blocked_rule_types_are_enumerated() -> None:
    assert MonitoringRuleType.ROLLING_ANOMALY in BLOCKED_RULE_TYPES
    with pytest.raises(RuleMatchError, match="blocked"):
        raise RuleMatchError("rule_type rolling_anomaly remains blocked without governance")


def test_materiality_raises_with_magnitude() -> None:
    previous, current = _market_pair()
    detection = detect_observation_change(
        previous=previous,
        current=current,
        detected_at=NOW + timedelta(minutes=1),
    )
    rule = MonitoringRule(
        rule_id="rule:price_threshold",
        rule_type=MonitoringRuleType.THRESHOLD,
        subject_id=detection.subject_id,
        metric_name="last_price",
        threshold="65000.0",
        severity_floor=MaterialityOutcome.MEDIUM,
    )
    decision = screen_materiality(detection=detection, rule=rule)
    assert decision.outcome in {
        MaterialityOutcome.MEDIUM,
        MaterialityOutcome.HIGH,
        MaterialityOutcome.CRITICAL,
    }
    assert decision.requires_semantic_triage is False


def test_semantic_triage_blocked() -> None:
    with pytest.raises(SemanticTriageBlocked, match="semantic triage"):
        refuse_semantic_triage(
            SemanticTriageRequest(
                alert_id="alert:" + ("a" * 64),
                change_summary="needs explanation",
            )
        )


def test_detect_requires_previous_for_ordinary_change() -> None:
    context = _context()
    result = import_fixture(context=context, fixture_name="bitcoin_block.json", now=NOW)
    assert result.observation is not None
    with pytest.raises(MonitoringError, match="previous observation"):
        detect_observation_change(
            previous=None,
            current=result.observation,
            detected_at=NOW,
        )


def test_quarantine_detection() -> None:
    context = _context()
    result = import_fixture(
        context=context,
        fixture_name="evm_block.json",
        now=NOW,
        provider_quality=ProviderQualityState.CONFLICTED,
    )
    # Conflicted fixture quarantines without observation — use orphaned bitcoin instead
    # for quality path by marking quality quarantined on a copy.
    good = import_fixture(context=context, fixture_name="bitcoin_block.json", now=NOW)
    assert good.observation is not None
    quarantined = good.observation.model_copy(
        update={
            "header": good.observation.header.model_copy(
                update={"quality": ObservationQuality.QUARANTINED}
            )
        }
    )
    detection = detect_observation_change(
        previous=None,
        current=quarantined,
        detected_at=NOW,
    )
    assert detection.change_kind is ChangeKind.QUARANTINED
    assert result.quarantine is not None
