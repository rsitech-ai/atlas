"""Alert dedup, lifecycle, invalidation, and launch stub tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from rsi_atlas_collectors import import_fixture, mark_orphaned
from rsi_atlas_contracts import (
    AlertLifecycle,
    ArtifactCommandContext,
    InvalidationReason,
    MaterialityOutcome,
    MonitoringRule,
    MonitoringRuleType,
    QueryFamily,
    RetrievalDataPlane,
    RetrievalPlan,
    RetrievalStep,
    retrieval_plan_hash,
)
from rsi_atlas_monitoring import (
    AlertTransitionError,
    LaunchValidationError,
    build_alert,
    dedupe_or_create,
    detect_observation_change,
    initial_alert_event,
    invalidate_from_detection,
    launch_targeted_research,
    match_rules,
    screen_materiality,
    transition_alert,
)

TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000002")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000000003")
TRACE_ID = UUID("00000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
REPORT_ID = "report:" + ("e" * 64)


def _context() -> ArtifactCommandContext:
    return ArtifactCommandContext(
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        trace_id=TRACE_ID,
    )


def _market_alert():
    context = _context()
    first = import_fixture(context=context, fixture_name="market_tick.json", now=NOW)
    assert first.observation is not None
    second = import_fixture(
        context=context,
        fixture_name="market_tick.json",
        now=NOW + timedelta(minutes=1),
    )
    assert second.observation is not None
    current = second.observation.model_copy(
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
    detection = detect_observation_change(
        previous=first.observation,
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
    decision = screen_materiality(detection=detection, rule=rule)
    alert = build_alert(
        detection=detection,
        rule=rule,
        decision=decision,
        affected_report_ids=(REPORT_ID,),
    )
    return alert, detection, rule, decision


def test_dedup_collapses_duplicate_alerts() -> None:
    alert, _, _, _ = _market_alert()
    again, _, _, _ = _market_alert()
    assert alert.dedup_key == again.dedup_key
    kept, created = dedupe_or_create(candidate=again, existing_by_dedup={alert.dedup_key: alert})
    assert created is False
    assert kept.alert_id == alert.alert_id


def test_lifecycle_append_only_and_illegal_transition() -> None:
    alert, _, _, _ = _market_alert()
    event = initial_alert_event(alert=alert)
    assert event.to_status is AlertLifecycle.DETECTED
    updated, next_event = transition_alert(
        alert=alert,
        to_status=AlertLifecycle.VALIDATED,
        recorded_at=NOW + timedelta(minutes=2),
    )
    assert updated.status is AlertLifecycle.VALIDATED
    assert next_event.from_status is AlertLifecycle.DETECTED
    with pytest.raises(AlertTransitionError, match="illegal"):
        transition_alert(
            alert=alert,
            to_status=AlertLifecycle.RESOLVED,
            recorded_at=NOW + timedelta(minutes=3),
        )


def test_orphan_invalidates_research() -> None:
    context = _context()
    result = import_fixture(context=context, fixture_name="bitcoin_block.json", now=NOW)
    assert result.observation is not None
    orphaned = mark_orphaned(result.observation)
    detection = detect_observation_change(
        previous=result.observation,
        current=orphaned,
        detected_at=NOW + timedelta(seconds=1),
    )
    record = invalidate_from_detection(
        detection=detection,
        affected_report_ids=(REPORT_ID,),
    )
    assert record.reason is InvalidationReason.ORPHANED_OBSERVATION
    assert REPORT_ID in record.affected_report_ids
    assert record.envelope_id == orphaned.header.envelope_id


def test_targeted_research_launch_stub() -> None:
    alert, _, _, _ = _market_alert()
    query_id = uuid4()
    steps = (
        RetrievalStep(
            step_id="dense_main",
            data_plane=RetrievalDataPlane.DENSE_DOCUMENT,
            retriever="fixture_dense",
            query_text="material price change impact",
            top_k=8,
            required=True,
            expected_evidence="supporting passages",
        ),
    )
    plan = RetrievalPlan(
        plan_id=uuid4(),
        query_id=query_id,
        query_family=QueryFamily.EVENT_INVESTIGATION,
        steps=steps,
        plan_hash=retrieval_plan_hash(
            query_id=query_id,
            query_family=QueryFamily.EVENT_INVESTIGATION,
            steps=steps,
        ),
    )
    launch = launch_targeted_research(alert=alert, plan=plan, recorded_at=NOW)
    assert launch.status == "recorded_stub"
    assert launch.alert_id == alert.alert_id

    with pytest.raises(Exception, match="blocked"):
        RetrievalStep(
            step_id="chain_only",
            data_plane=RetrievalDataPlane.CHAIN_SNAPSHOT,
            retriever="blocked",
            query_text="x",
            top_k=1,
            required=True,
            expected_evidence="blocked",
        )


def test_launch_rejects_empty_plan_via_validation() -> None:
    alert, _, _, _ = _market_alert()
    # Bypass contract min_length by using validate path with a mutated object is hard;
    # instead ensure LaunchValidationError wraps PlanValidationError for empty required.
    query_id = uuid4()
    steps = (
        RetrievalStep(
            step_id="optional_only",
            data_plane=RetrievalDataPlane.LEXICAL,
            retriever="fixture_lexical",
            query_text="optional",
            top_k=4,
            required=False,
            expected_evidence="optional",
        ),
    )
    plan = RetrievalPlan(
        plan_id=uuid4(),
        query_id=query_id,
        query_family=QueryFamily.EXACT_LOOKUP,
        steps=steps,
        plan_hash=retrieval_plan_hash(
            query_id=query_id,
            query_family=QueryFamily.EXACT_LOOKUP,
            steps=steps,
        ),
    )
    with pytest.raises(LaunchValidationError, match="required"):
        launch_targeted_research(alert=alert, plan=plan, recorded_at=NOW)
