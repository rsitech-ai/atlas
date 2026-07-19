"""Research invalidation records for orphaned/quarantined inputs."""

from __future__ import annotations

from datetime import datetime

from rsi_atlas_contracts import (
    ArtifactCommandContext,
    ChangeDetection,
    ChangeKind,
    InvalidationReason,
    ResearchInvalidation,
    research_invalidation_id,
)

from rsi_atlas_monitoring.errors import MonitoringError


def invalidate_from_detection(
    *,
    detection: ChangeDetection,
    affected_report_ids: tuple[str, ...] = (),
    affected_assertion_ids: tuple[str, ...] = (),
    alert_id: str | None = None,
    recorded_at: datetime | None = None,
) -> ResearchInvalidation:
    reason = _reason_for(detection.change_kind)
    stamped = recorded_at or detection.detected_at
    return ResearchInvalidation(
        context=detection.context,
        invalidation_id=research_invalidation_id(
            reason=reason,
            subject_id=detection.subject_id,
            observation_id=detection.current_observation_id,
            envelope_id=detection.current_envelope_id,
            recorded_at=stamped,
        ),
        reason=reason,
        subject_id=detection.subject_id,
        observation_id=detection.current_observation_id,
        envelope_id=detection.current_envelope_id,
        alert_id=alert_id,
        affected_report_ids=affected_report_ids,
        affected_assertion_ids=affected_assertion_ids,
        recorded_at=stamped,
        summary=f"{reason.value} for {detection.subject_id}",
    )


def invalidate_quarantine(
    *,
    context: ArtifactCommandContext,
    subject_id: str,
    envelope_id: str,
    observation_id: str | None = None,
    affected_report_ids: tuple[str, ...] = (),
    recorded_at: datetime,
) -> ResearchInvalidation:
    return ResearchInvalidation(
        context=context,
        invalidation_id=research_invalidation_id(
            reason=InvalidationReason.QUARANTINED_INPUT,
            subject_id=subject_id,
            observation_id=observation_id,
            envelope_id=envelope_id,
            recorded_at=recorded_at,
        ),
        reason=InvalidationReason.QUARANTINED_INPUT,
        subject_id=subject_id,
        observation_id=observation_id,
        envelope_id=envelope_id,
        affected_report_ids=affected_report_ids,
        recorded_at=recorded_at,
        summary=f"quarantined input for {subject_id}",
    )


def _reason_for(change_kind: ChangeKind) -> InvalidationReason:
    if change_kind is ChangeKind.ORPHANED:
        return InvalidationReason.ORPHANED_OBSERVATION
    if change_kind is ChangeKind.QUARANTINED:
        return InvalidationReason.QUARANTINED_INPUT
    if change_kind in {
        ChangeKind.THRESHOLD_BREACH,
        ChangeKind.RATE_OF_CHANGE,
        ChangeKind.FINALITY_TRANSITION,
        ChangeKind.QUALITY_TRANSITION,
    }:
        return InvalidationReason.MATERIAL_CHANGE
    raise MonitoringError(f"change_kind {change_kind.value} does not invalidate research")
