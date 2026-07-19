"""Leakage-safe feature computation from observations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from rsi_atlas_contracts import (
    BitcoinBlockObservation,
    FeatureDefinition,
    FeatureLifecycle,
    FeatureValue,
    Observation,
    ObservationQuality,
    SourceFamily,
    feature_eligible,
)

from rsi_atlas_collectors.errors import FeatureLeakageError, FixtureNormalizationError

BTC_FEE_FEATURE = FeatureDefinition(
    feature_id="btc_fee_regime",
    entity_type="asset",
    grain="block",
    value_type="decimal",
    unit="sat_vb",
    lookback="1_block",
    availability_delay="0s",
    implementation_version="feat_v1",
    lifecycle=FeatureLifecycle.EXPERIMENTAL,
)


def compute_btc_fee_regime(
    *,
    observation: Observation,
    as_of: datetime,
    calculation_run_id: UUID | None = None,
) -> FeatureValue:
    if observation.header.source_family is not SourceFamily.BITCOIN:
        raise FixtureNormalizationError("btc_fee_regime requires bitcoin observation")
    if not isinstance(observation.payload, BitcoinBlockObservation):
        raise FixtureNormalizationError("btc_fee_regime requires bitcoin block payload")
    available = observation.header.available_time
    if not feature_eligible(available_time=available, as_of=as_of):
        raise FeatureLeakageError(
            "feature.available_time must be <= investigation.as_of "
            f"(available={available.isoformat()}, as_of={as_of.isoformat()})"
        )
    subject = observation.header.subject_ids[0]
    return FeatureValue(
        feature_id=BTC_FEE_FEATURE.feature_id,
        subject_id=subject,
        effective_time=observation.header.valid_time,
        available_time=available,
        value=observation.payload.fee_rate_sat_vb,
        unit=BTC_FEE_FEATURE.unit,
        input_observation_ids=(observation.header.observation_id,),
        calculation_run_id=calculation_run_id or uuid4(),
        quality=ObservationQuality.VALID,
        implementation_version=BTC_FEE_FEATURE.implementation_version,
    )
