"""Comparison matrix and cross-chain timeline builders."""

from __future__ import annotations

from datetime import datetime
from typing import assert_never

from rsi_atlas_contracts import (
    Alert,
    ArtifactCommandContext,
    ComparisonAxis,
    ComparisonCell,
    ComparisonMatrix,
    CrossChainTimeline,
    MarketTick,
    Observation,
    TimelineEvent,
    TimelineEventKind,
    comparison_matrix_id,
    cross_chain_timeline_id,
)

from rsi_atlas_monitoring.errors import MonitoringError


def build_comparison_matrix(
    *,
    context: ArtifactCommandContext,
    observations: tuple[Observation, ...],
    axes: tuple[ComparisonAxis, ...],
    as_of: datetime,
) -> ComparisonMatrix:
    if not observations:
        raise MonitoringError("comparison matrix requires at least one observation")
    subjects = tuple(dict.fromkeys(obs.header.subject_ids[0] for obs in observations))
    cells: list[ComparisonCell] = []
    for observation in observations:
        subject_id = observation.header.subject_ids[0]
        for axis in axes:
            value = _axis_value(observation=observation, axis=axis)
            if value is None:
                continue
            cells.append(
                ComparisonCell(
                    subject_id=subject_id,
                    axis=axis,
                    value=value,
                    observation_id=observation.header.observation_id,
                    envelope_id=observation.header.envelope_id,
                    source_family=observation.header.source_family.value,
                    as_of=as_of,
                )
            )
    if not cells:
        raise MonitoringError("comparison matrix produced no cells for requested axes")
    return ComparisonMatrix(
        context=context,
        matrix_id=comparison_matrix_id(subjects=subjects, axes=axes, as_of=as_of),
        axes=axes,
        subjects=subjects,
        cells=tuple(cells),
        as_of=as_of,
    )


def build_cross_chain_timeline(
    *,
    context: ArtifactCommandContext,
    observations: tuple[Observation, ...],
    alerts: tuple[Alert, ...] = (),
    as_of: datetime,
) -> CrossChainTimeline:
    if not observations and not alerts:
        raise MonitoringError("timeline requires observations or alerts")
    subjects = tuple(
        dict.fromkeys(
            [obs.header.subject_ids[0] for obs in observations]
            + [alert.subject_id for alert in alerts]
        )
    )
    events: list[TimelineEvent] = []
    for observation in observations:
        events.append(
            TimelineEvent(
                event_kind=TimelineEventKind.OBSERVATION,
                subject_id=observation.header.subject_ids[0],
                event_time=observation.header.event_time,
                observation_id=observation.header.observation_id,
                envelope_id=observation.header.envelope_id,
                summary=f"{observation.header.source_family.value} observation",
                source_family=observation.header.source_family.value,
            )
        )
    for alert in alerts:
        events.append(
            TimelineEvent(
                event_kind=TimelineEventKind.ALERT,
                subject_id=alert.subject_id,
                event_time=alert.event_time,
                observation_id=alert.current_observation_id,
                envelope_id=alert.current_envelope_id,
                alert_id=alert.alert_id,
                summary=alert.change_summary,
                source_family=None,
            )
        )
    events.sort(key=lambda item: item.event_time)
    return CrossChainTimeline(
        context=context,
        timeline_id=cross_chain_timeline_id(subjects=subjects, as_of=as_of),
        subjects=subjects,
        events=tuple(events),
        as_of=as_of,
    )


def _axis_value(*, observation: Observation, axis: ComparisonAxis) -> str | None:
    if axis is ComparisonAxis.SOURCE_FAMILY:
        return observation.header.source_family.value
    if axis is ComparisonAxis.QUALITY:
        return observation.header.quality.value
    if axis is ComparisonAxis.FINALITY:
        if observation.header.finality is None:
            return None
        return str(observation.header.finality.value)
    if axis is ComparisonAxis.MARKET_PRICE:
        if isinstance(observation.payload, MarketTick):
            return observation.payload.last
        return None
    if axis is ComparisonAxis.GOVERNANCE_STATE:
        if observation.header.source_family.value == "governance":
            return str(getattr(observation.payload, "status", "unknown"))
        return None
    if axis is ComparisonAxis.GITHUB_RELEASE:
        if observation.header.source_family.value == "github":
            return str(getattr(observation.payload, "ref", "unknown"))
        return None
    assert_never(axis)
