from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from rsi_atlas_contracts import ComponentStatus, HealthState, RuntimeProfile, SystemStatus

STATE_PRIORITY = {
    HealthState.HEALTHY: 0,
    HealthState.DEGRADED: 1,
    HealthState.REPAIRABLE: 2,
    HealthState.BLOCKED: 3,
    HealthState.UNSAFE: 4,
}


def utc_now() -> datetime:
    return datetime.now(UTC)


def build_system_status(
    *,
    clock: Callable[[], datetime] = utc_now,
    profile: RuntimeProfile,
    components: Sequence[ComponentStatus],
) -> SystemStatus:
    checks = tuple(components)
    if not checks:
        raise ValueError("RSI Atlas diagnostics require at least one component")
    state = max(checks, key=lambda check: STATE_PRIORITY[check.state]).state
    return SystemStatus(
        schema_version="1.1.0",
        product="RSI Atlas Engine",
        profile=profile,
        state=state,
        checked_at=clock(),
        components=checks,
    )
