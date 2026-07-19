"""Typed errors for the monitoring package."""


class MonitoringError(Exception):
    """Base monitoring failure."""


class SemanticTriageBlocked(MonitoringError):
    """Raised when semantic triage is requested before promotion."""


class AlertTransitionError(MonitoringError):
    """Raised on illegal alert lifecycle transitions."""


class RuleMatchError(MonitoringError):
    """Raised when a rule cannot be evaluated."""


class LaunchValidationError(MonitoringError):
    """Raised when a targeted research launch stub fails plan validation."""
