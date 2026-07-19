"""Non-trading research signals derived from observations/features."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from rsi_atlas_contracts import (
    FeatureValue,
    Observation,
    ResearchSignal,
    SignalKind,
)

from rsi_atlas_collectors.errors import FixtureNormalizationError

# ponytail: naive threshold for development fixture proof only; upgrade = calibrated detector.
_FEE_REGIME_THRESHOLD = Decimal("10")


def detect_fee_regime_signal(
    *,
    observation: Observation,
    feature: FeatureValue,
    detected_at: datetime,
) -> ResearchSignal | None:
    if feature.feature_id != "btc_fee_regime":
        raise FixtureNormalizationError("unsupported feature for fee regime signal")
    if Decimal(feature.value) < _FEE_REGIME_THRESHOLD:
        return None
    return ResearchSignal(
        signal_id=uuid4(),
        kind=SignalKind.FEE_REGIME_CHANGE,
        subject_ids=observation.header.subject_ids,
        observation_ids=(observation.header.observation_id,),
        feature_ids=(feature.feature_id,),
        summary=(
            f"Bitcoin fee regime {feature.value} {feature.unit} exceeds "
            f"development threshold {_FEE_REGIME_THRESHOLD}."
        ),
        detected_at=detected_at,
    )
