"""Offline fixture collectors and fail-closed live/analytics stubs."""

from rsi_atlas_collectors.analytics_stubs import analytics_gates, require_postgres_only
from rsi_atlas_collectors.errors import (
    AnalyticsBackendBlocked,
    CollectorError,
    FeatureLeakageError,
    FixtureNormalizationError,
    LiveCollectorBlocked,
    MarketSequenceError,
    QualityQuarantine,
)
from rsi_atlas_collectors.features import BTC_FEE_FEATURE, compute_btc_fee_regime
from rsi_atlas_collectors.live_stubs import refuse_live_collect, require_offline_mode
from rsi_atlas_collectors.market import require_contiguous_sequence
from rsi_atlas_collectors.pipeline import (
    FIXTURE_ROOT,
    FixtureImportResult,
    collector_definition_for,
    import_fixture,
    load_fixture_bytes,
)
from rsi_atlas_collectors.reorg import mark_orphaned
from rsi_atlas_collectors.signals import detect_fee_regime_signal

__all__ = [
    "BTC_FEE_FEATURE",
    "FIXTURE_ROOT",
    "AnalyticsBackendBlocked",
    "CollectorError",
    "FeatureLeakageError",
    "FixtureImportResult",
    "FixtureNormalizationError",
    "LiveCollectorBlocked",
    "MarketSequenceError",
    "QualityQuarantine",
    "analytics_gates",
    "collector_definition_for",
    "compute_btc_fee_regime",
    "detect_fee_regime_signal",
    "import_fixture",
    "load_fixture_bytes",
    "mark_orphaned",
    "refuse_live_collect",
    "require_contiguous_sequence",
    "require_offline_mode",
    "require_postgres_only",
]
