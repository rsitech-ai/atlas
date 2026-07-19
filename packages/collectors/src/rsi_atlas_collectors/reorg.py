"""Reorganization / orphan handling for chain observations."""

from __future__ import annotations

from dataclasses import dataclass

from rsi_atlas_contracts import (
    FinalityState,
    Observation,
    ObservationQuality,
    SourceFamily,
)

from rsi_atlas_collectors.errors import FixtureNormalizationError


@dataclass(frozen=True, slots=True)
class ReorgEvent:
    family: str
    from_height: int
    to_height: int
    orphaned_observation_ids: tuple[str, ...]


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


def apply_reorg(
    *,
    observations: tuple[Observation, ...],
    from_height: int,
    to_height: int,
    height_field: str = "height",
) -> tuple[tuple[Observation, ...], ReorgEvent]:
    """Orphan bitcoin/evm observations with height in (to_height, from_height].

    ponytail: ceiling=payload height field only; upgrade=chain-native tip index.
    """
    if to_height > from_height:
        raise ValueError("reorg to_height must be <= from_height")
    rewritten: list[Observation] = []
    orphaned_ids: list[str] = []
    family = "unknown"
    for obs in observations:
        family = obs.header.source_family.value
        payload = obs.payload.model_dump(mode="python")
        raw_height = payload.get(height_field)
        try:
            height_val = int(raw_height) if raw_height is not None else None
        except (TypeError, ValueError):
            height_val = None
        if (
            height_val is not None
            and to_height < height_val <= from_height
            and obs.header.source_family in {SourceFamily.BITCOIN, SourceFamily.EVM}
        ):
            orphaned = mark_orphaned(obs)
            rewritten.append(orphaned)
            orphaned_ids.append(orphaned.header.observation_id)
        else:
            rewritten.append(obs)
    event = ReorgEvent(
        family=family,
        from_height=from_height,
        to_height=to_height,
        orphaned_observation_ids=tuple(orphaned_ids),
    )
    return tuple(rewritten), event


__all__ = ["ReorgEvent", "apply_reorg", "mark_orphaned"]
