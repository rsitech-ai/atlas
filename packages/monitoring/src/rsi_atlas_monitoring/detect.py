"""Deterministic change detection over observation pairs."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from rsi_atlas_contracts import (
    ChangeDetection,
    ChangeKind,
    DeterministicMeasurement,
    FinalityState,
    MarketTick,
    Observation,
    ObservationQuality,
)

from rsi_atlas_monitoring.errors import MonitoringError


def detect_observation_change(
    *,
    previous: Observation | None,
    current: Observation,
    detected_at: datetime,
) -> ChangeDetection:
    """Compare previous/current observations and emit deterministic measurements."""
    context = current.context
    subject_id = current.header.subject_ids[0]
    current_obs_id = current.header.observation_id
    current_env_id = current.header.envelope_id

    if current.header.finality is FinalityState.ORPHANED:
        return ChangeDetection(
            context=context,
            change_kind=ChangeKind.ORPHANED,
            subject_id=subject_id,
            previous_observation_id=(None if previous is None else previous.header.observation_id),
            current_observation_id=current_obs_id,
            previous_envelope_id=None if previous is None else previous.header.envelope_id,
            current_envelope_id=current_env_id,
            event_time=current.header.event_time,
            detected_at=detected_at,
            measurements=(
                DeterministicMeasurement(
                    name="finality",
                    previous_value=(
                        "none"
                        if previous is None or previous.header.finality is None
                        else str(previous.header.finality.value)
                    ),
                    current_value=FinalityState.ORPHANED.value,
                    unit="state",
                    delta=None,
                ),
            ),
            confidence="1.0",
        )

    if current.header.quality in {
        ObservationQuality.QUARANTINED,
        ObservationQuality.CONFLICTED,
    }:
        return ChangeDetection(
            context=context,
            change_kind=ChangeKind.QUARANTINED,
            subject_id=subject_id,
            previous_observation_id=(None if previous is None else previous.header.observation_id),
            current_observation_id=current_obs_id,
            previous_envelope_id=None if previous is None else previous.header.envelope_id,
            current_envelope_id=current_env_id,
            event_time=current.header.event_time,
            detected_at=detected_at,
            measurements=(
                DeterministicMeasurement(
                    name="quality",
                    previous_value=("none" if previous is None else previous.header.quality.value),
                    current_value=current.header.quality.value,
                    unit="state",
                    delta=None,
                ),
            ),
            confidence="1.0",
        )

    if previous is None:
        raise MonitoringError("previous observation required for non-orphan/quarantine detect")

    if previous.header.subject_ids[0] != subject_id:
        raise MonitoringError("previous and current observations must share subject_id")

    # Finality / quality transitions take precedence over metric deltas.
    if (
        previous.header.finality is not None
        and current.header.finality is not None
        and previous.header.finality != current.header.finality
    ):
        return ChangeDetection(
            context=context,
            change_kind=ChangeKind.FINALITY_TRANSITION,
            subject_id=subject_id,
            previous_observation_id=previous.header.observation_id,
            current_observation_id=current_obs_id,
            previous_envelope_id=previous.header.envelope_id,
            current_envelope_id=current_env_id,
            event_time=current.header.event_time,
            detected_at=detected_at,
            measurements=(
                DeterministicMeasurement(
                    name="finality",
                    previous_value=str(previous.header.finality.value),
                    current_value=str(current.header.finality.value),
                    unit="state",
                    delta=None,
                ),
            ),
            confidence="1.0",
        )

    if previous.header.quality != current.header.quality:
        return ChangeDetection(
            context=context,
            change_kind=ChangeKind.QUALITY_TRANSITION,
            subject_id=subject_id,
            previous_observation_id=previous.header.observation_id,
            current_observation_id=current_obs_id,
            previous_envelope_id=previous.header.envelope_id,
            current_envelope_id=current_env_id,
            event_time=current.header.event_time,
            detected_at=detected_at,
            measurements=(
                DeterministicMeasurement(
                    name="quality",
                    previous_value=previous.header.quality.value,
                    current_value=current.header.quality.value,
                    unit="state",
                    delta=None,
                ),
            ),
            confidence="1.0",
        )

    if isinstance(previous.payload, MarketTick) and isinstance(current.payload, MarketTick):
        prev_last = Decimal(previous.payload.last)
        cur_last = Decimal(current.payload.last)
        delta = cur_last - prev_last
        if delta == 0:
            change_kind = ChangeKind.NO_MATERIAL_CHANGE
            confidence = "1.0"
        else:
            change_kind = ChangeKind.RATE_OF_CHANGE
            confidence = "0.95"
        return ChangeDetection(
            context=context,
            change_kind=change_kind,
            subject_id=subject_id,
            previous_observation_id=previous.header.observation_id,
            current_observation_id=current_obs_id,
            previous_envelope_id=previous.header.envelope_id,
            current_envelope_id=current_env_id,
            event_time=current.header.event_time,
            detected_at=detected_at,
            measurements=(
                DeterministicMeasurement(
                    name="last_price",
                    previous_value=previous.payload.last,
                    current_value=current.payload.last,
                    unit="quote",
                    delta=format(delta, "f"),
                ),
            ),
            confidence=confidence,
        )

    # Generic no-op when payloads share type but no tracked metric moved.
    return ChangeDetection(
        context=context,
        change_kind=ChangeKind.NO_MATERIAL_CHANGE,
        subject_id=subject_id,
        previous_observation_id=previous.header.observation_id,
        current_observation_id=current_obs_id,
        previous_envelope_id=previous.header.envelope_id,
        current_envelope_id=current_env_id,
        event_time=current.header.event_time,
        detected_at=detected_at,
        measurements=(
            DeterministicMeasurement(
                name="observation_id",
                previous_value=previous.header.observation_id,
                current_value=current_obs_id,
                unit="id",
                delta=None,
            ),
        ),
        confidence="1.0",
    )
