from datetime import UTC, datetime

import pytest
from rsi_atlas_contracts.system_status import (
    ComponentGroup,
    ComponentStatus,
    HealthState,
    RuntimeProfile,
)
from rsi_atlas_engine.diagnostics import build_system_status

CHECKED_AT = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
HEALTHY = ComponentStatus(
    component_id="engine_runtime",
    title="Engine Runtime",
    group=ComponentGroup.ENGINE,
    state=HealthState.HEALTHY,
    summary="The local engine can evaluate runtime diagnostics.",
)
DEGRADED = ComponentStatus(
    component_id="model_registry",
    title="Model Registry",
    group=ComponentGroup.RESOURCES,
    state=HealthState.DEGRADED,
    summary="No qualified local model or provider is available in Phase 1.",
)
BLOCKED = ComponentStatus(
    component_id="database",
    title="Database",
    group=ComponentGroup.STORAGE,
    state=HealthState.BLOCKED,
    summary="PostgreSQL is unavailable.",
    remediation="Start the project-owned PostgreSQL runtime.",
)


def test_build_system_status_uses_exact_profile_components_and_severity() -> None:
    status = build_system_status(
        clock=lambda: CHECKED_AT,
        profile=RuntimeProfile.OFFLINE,
        components=(HEALTHY, DEGRADED),
    )

    assert status.schema_version == "1.1.0"
    assert status.checked_at == CHECKED_AT
    assert status.profile is RuntimeProfile.OFFLINE
    assert status.state is HealthState.DEGRADED
    assert status.components == (HEALTHY, DEGRADED)


def test_build_system_status_uses_most_severe_component_state() -> None:
    status = build_system_status(
        clock=lambda: CHECKED_AT,
        profile=RuntimeProfile.OFFLINE,
        components=(DEGRADED, BLOCKED),
    )

    assert status.state is HealthState.BLOCKED
    assert status.components == (DEGRADED, BLOCKED)


def test_build_system_status_rejects_an_empty_component_set() -> None:
    with pytest.raises(ValueError, match="at least one component"):
        build_system_status(
            clock=lambda: CHECKED_AT,
            profile=RuntimeProfile.OFFLINE,
            components=(),
        )
