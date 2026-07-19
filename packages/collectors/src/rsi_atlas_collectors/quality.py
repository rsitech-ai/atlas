"""Observation quality checks that quarantine instead of dropping."""

from __future__ import annotations

from rsi_atlas_contracts import (
    Observation,
    ObservationQuality,
    ProviderQualityState,
)

from rsi_atlas_collectors.errors import QualityQuarantine


def evaluate_observation(observation: Observation) -> Observation:
    reasons: list[str] = []
    if observation.header.provider_quality is ProviderQualityState.CONFLICTED:
        reasons.append("provider_disagreement_conflicted")
    if observation.header.provider_quality is ProviderQualityState.INVALID:
        reasons.append("provider_quality_invalid")
    if observation.header.quality is ObservationQuality.QUARANTINED:
        reasons.append("header_marked_quarantined")
    if reasons:
        raise QualityQuarantine(tuple(reasons))
    return observation
