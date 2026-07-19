"""Typed failures for the offline collector pipeline."""


class CollectorError(RuntimeError):
    """Base collector failure."""


class LiveCollectorBlocked(CollectorError):
    """Raised when a live/monitored acquisition mode is requested."""


class AnalyticsBackendBlocked(CollectorError):
    """Raised when DuckDB/Parquet is requested without governance."""


class FixtureNormalizationError(CollectorError):
    """Raised when fixture payload cannot be normalized."""


class QualityQuarantine(CollectorError):
    """Raised when quality checks quarantine rather than publish."""

    def __init__(self, reasons: tuple[str, ...]) -> None:
        self.reasons = reasons
        super().__init__(", ".join(reasons))


class FeatureLeakageError(CollectorError):
    """Raised when a feature would leak future information."""


class MarketSequenceError(CollectorError):
    """Raised when market sequence continuity fails and resnapshot is required."""
