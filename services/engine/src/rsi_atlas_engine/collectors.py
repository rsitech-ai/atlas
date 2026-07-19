"""Offline fixture collector service for development loopback APIs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from json import loads
from typing import Protocol

from rsi_atlas_collectors import (
    FixtureImportResult,
    compute_btc_fee_regime,
    detect_fee_regime_signal,
    import_fixture,
    mark_orphaned,
)
from rsi_atlas_contracts import (
    ArtifactCommandContext,
    FeatureValue,
    Observation,
    ProviderQualityState,
    ResearchSignal,
)
from rsi_atlas_storage import ObservationRepository, PostgresDatabase


class CollectorPort(Protocol):
    def import_fixture(
        self,
        *,
        context: ArtifactCommandContext,
        fixture_name: str,
        provider_quality: ProviderQualityState = ProviderQualityState.SINGLE_SOURCE,
    ) -> FixtureImportResult: ...

    def list_observations(
        self,
        *,
        context: ArtifactCommandContext,
        as_of: datetime,
        subject_id: str | None = None,
    ) -> list[Observation]: ...

    def get_observation(
        self, *, context: ArtifactCommandContext, observation_id: str
    ) -> Observation | None: ...


@dataclass(frozen=True, slots=True)
class CollectorServices:
    repository: ObservationRepository

    @classmethod
    def from_database(cls, database: PostgresDatabase) -> CollectorServices:
        return cls(repository=ObservationRepository(database))

    def import_fixture(
        self,
        *,
        context: ArtifactCommandContext,
        fixture_name: str,
        provider_quality: ProviderQualityState = ProviderQualityState.SINGLE_SOURCE,
    ) -> FixtureImportResult:
        result = import_fixture(
            context=context,
            fixture_name=fixture_name,
            now=datetime.now(tz=UTC),
            provider_quality=provider_quality,
        )
        self.repository.save_envelope(
            envelope=result.envelope,
            payload=loads(result.payload_bytes.decode("utf-8")),
        )
        if result.quarantine is not None:
            self.repository.save_quarantine(quarantine=result.quarantine)
            return result
        if result.observation is not None:
            self.repository.save_observation(observation=result.observation)
        return result

    def list_observations(
        self,
        *,
        context: ArtifactCommandContext,
        as_of: datetime,
        subject_id: str | None = None,
    ) -> list[Observation]:
        rows = self.repository.list_as_of(context=context, as_of=as_of, subject_id=subject_id)
        return [Observation.model_validate(row) for row in rows]

    def get_observation(
        self, *, context: ArtifactCommandContext, observation_id: str
    ) -> Observation | None:
        row = self.repository.get_observation(context=context, observation_id=observation_id)
        if row is None:
            return None
        return Observation.model_validate(row)

    def orphan_observation(
        self, *, context: ArtifactCommandContext, observation_id: str
    ) -> Observation:
        current = self.get_observation(context=context, observation_id=observation_id)
        if current is None:
            raise LookupError("observation not found")
        orphaned = mark_orphaned(current)
        self.repository.update_observation_quality(observation=orphaned)
        return orphaned

    def compute_feature(
        self,
        *,
        context: ArtifactCommandContext,
        observation_id: str,
        as_of: datetime,
    ) -> FeatureValue:
        observation = self.get_observation(context=context, observation_id=observation_id)
        if observation is None:
            raise LookupError("observation not found")
        return compute_btc_fee_regime(observation=observation, as_of=as_of)

    def detect_signal(
        self,
        *,
        context: ArtifactCommandContext,
        observation_id: str,
        as_of: datetime,
    ) -> ResearchSignal | None:
        observation = self.get_observation(context=context, observation_id=observation_id)
        if observation is None:
            raise LookupError("observation not found")
        feature = compute_btc_fee_regime(observation=observation, as_of=as_of)
        return detect_fee_regime_signal(
            observation=observation,
            feature=feature,
            detected_at=as_of,
        )
