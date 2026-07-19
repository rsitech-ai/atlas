"""Reorganization / orphan handling stub for chain observations."""

from __future__ import annotations

from rsi_atlas_contracts import (
    FinalityState,
    Observation,
    ObservationQuality,
    SourceFamily,
)

from rsi_atlas_collectors.errors import FixtureNormalizationError


def mark_orphaned(observation: Observation) -> Observation:
    """Return a new observation marked orphaned while preserving identity/history fields."""
    if observation.header.source_family not in {
        SourceFamily.BITCOIN,
        SourceFamily.EVM,
    }:
        raise FixtureNormalizationError("orphan marking applies to bitcoin/evm only")
    header = observation.header.model_copy(
        update={
            "quality": ObservationQuality.ORPHANED,
            "finality": FinalityState.ORPHANED,
        }
    )
    return Observation(
        context=observation.context,
        header=header,
        payload=observation.payload,
    )
