from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from rsi_atlas_contracts import ComponentStatus, HealthState, RuntimeProfile, SystemStatus

FOUNDATION_CHECKS = (
    ComponentStatus(
        component_id="engine_runtime",
        title="Engine Runtime",
        state=HealthState.HEALTHY,
        summary="The local engine can evaluate foundation diagnostics.",
    ),
    ComponentStatus(
        component_id="offline_policy",
        title="Offline Policy",
        state=HealthState.HEALTHY,
        summary="Remote collectors, models, telemetry, and updates are disabled.",
    ),
    ComponentStatus(
        component_id="contract_api",
        title="Contract API",
        state=HealthState.HEALTHY,
        summary="The versioned local status contract is available.",
    ),
)

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
    components: Sequence[ComponentStatus] | None = None,
) -> SystemStatus:
    checks = tuple(components) if components is not None else FOUNDATION_CHECKS
    if not checks:
        raise ValueError("RSI Atlas diagnostics require at least one component")
    state = max(checks, key=lambda check: STATE_PRIORITY[check.state]).state
    return SystemStatus(
        schema_version="1.0.0",
        product="RSI Atlas Engine",
        profile=RuntimeProfile.OFFLINE,
        state=state,
        checked_at=clock(),
        components=checks,
    )
