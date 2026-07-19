"""Alert construction, deduplication, and lifecycle transitions."""

from __future__ import annotations

from datetime import datetime

from rsi_atlas_contracts import (
    ALERT_LIFECYCLE_TRANSITIONS,
    Alert,
    AlertEvent,
    AlertLifecycle,
    ChangeDetection,
    MaterialityDecision,
    MaterialityOutcome,
    MonitoringRule,
    alert_dedup_key,
    alert_event_id,
    alert_id,
)

from rsi_atlas_monitoring.errors import AlertTransitionError, MonitoringError


def build_alert(
    *,
    detection: ChangeDetection,
    rule: MonitoringRule,
    decision: MaterialityDecision,
    affected_report_ids: tuple[str, ...] = (),
    affected_assertion_ids: tuple[str, ...] = (),
) -> Alert:
    if decision.outcome is MaterialityOutcome.RECORD_ONLY:
        raise MonitoringError("record_only materiality does not create alerts")
    transition = _state_transition(detection)
    window_bucket = int(detection.detected_at.timestamp()) // rule.dedup_window_seconds
    dedup = alert_dedup_key(
        subject_id=detection.subject_id,
        rule_id=rule.rule_id,
        underlying_event_id=detection.current_observation_id,
        state_transition=transition,
        window_bucket=window_bucket,
    )
    return Alert(
        context=detection.context,
        alert_id=alert_id(dedup_key=dedup),
        dedup_key=dedup,
        rule_id=rule.rule_id,
        subject_id=detection.subject_id,
        severity=decision.outcome,
        status=AlertLifecycle.DETECTED,
        detected_at=detection.detected_at,
        event_time=detection.event_time,
        previous_observation_id=detection.previous_observation_id,
        current_observation_id=detection.current_observation_id,
        previous_envelope_id=detection.previous_envelope_id,
        current_envelope_id=detection.current_envelope_id,
        change_summary=decision.rationale,
        measurements=detection.measurements,
        affected_report_ids=affected_report_ids,
        affected_assertion_ids=affected_assertion_ids,
        confidence=detection.confidence,
    )


def initial_alert_event(*, alert: Alert) -> AlertEvent:
    return AlertEvent(
        context=alert.context,
        event_id=alert_event_id(
            alert_id_value=alert.alert_id,
            to_status=AlertLifecycle.DETECTED,
            recorded_at=alert.detected_at,
        ),
        alert_id=alert.alert_id,
        from_status=None,
        to_status=AlertLifecycle.DETECTED,
        recorded_at=alert.detected_at,
    )


def transition_alert(
    *,
    alert: Alert,
    to_status: AlertLifecycle,
    recorded_at: datetime,
    note: str = "",
) -> tuple[Alert, AlertEvent]:
    allowed = ALERT_LIFECYCLE_TRANSITIONS[alert.status]
    if to_status not in allowed:
        raise AlertTransitionError(
            f"illegal alert lifecycle transition {alert.status.value} -> {to_status.value}"
        )
    event = AlertEvent(
        context=alert.context,
        event_id=alert_event_id(
            alert_id_value=alert.alert_id,
            to_status=to_status,
            recorded_at=recorded_at,
        ),
        alert_id=alert.alert_id,
        from_status=alert.status,
        to_status=to_status,
        recorded_at=recorded_at,
        note=note,
    )
    updated = alert.model_copy(update={"status": to_status})
    return updated, event


def dedupe_or_create(
    *,
    candidate: Alert,
    existing_by_dedup: dict[str, Alert],
) -> tuple[Alert, bool]:
    """Return (alert, created). Duplicate detections reuse the open alert."""
    existing = existing_by_dedup.get(candidate.dedup_key)
    if existing is not None and existing.status not in {
        AlertLifecycle.RESOLVED,
        AlertLifecycle.DISMISSED,
        AlertLifecycle.SUPERSEDED,
    }:
        return existing, False
    return candidate, True


def _state_transition(detection: ChangeDetection) -> str:
    measurement = detection.measurements[0]
    return f"{measurement.previous_value}->{measurement.current_value}"
