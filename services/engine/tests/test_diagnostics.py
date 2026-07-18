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
HEALTHY_DATABASE = ComponentStatus(
    component_id="database",
    title="Database",
    group=ComponentGroup.STORAGE,
    state=HealthState.HEALTHY,
    summary="Database is healthy.",
)
ARTIFACT = ComponentStatus(
    component_id="artifact_store",
    title="Artifact Store",
    group=ComponentGroup.STORAGE,
    state=HealthState.HEALTHY,
    summary="Artifact store is healthy.",
)
OFFLINE = ComponentStatus(
    component_id="offline_policy",
    title="Offline Policy",
    group=ComponentGroup.PRIVACY,
    state=HealthState.HEALTHY,
    summary="Offline policy is healthy.",
)
TRACE = ComponentStatus(
    component_id="trace_store",
    title="Trace Store",
    group=ComponentGroup.OBSERVABILITY,
    state=HealthState.HEALTHY,
    summary="Trace store is healthy.",
)
RESOURCE = ComponentStatus(
    component_id="resource_policy",
    title="Resource Policy",
    group=ComponentGroup.RESOURCES,
    state=HealthState.HEALTHY,
    summary="Resource policy is healthy.",
)
CONTRACT = ComponentStatus(
    component_id="contract_api",
    title="Contract API",
    group=ComponentGroup.ENGINE,
    state=HealthState.HEALTHY,
    summary="Contract API is healthy.",
)


def _components(*, database: ComponentStatus = HEALTHY_DATABASE) -> tuple[ComponentStatus, ...]:
    return (HEALTHY, database, ARTIFACT, OFFLINE, TRACE, RESOURCE, DEGRADED, CONTRACT)


def test_build_system_status_uses_exact_profile_components_and_severity() -> None:
    status = build_system_status(
        clock=lambda: CHECKED_AT,
        profile=RuntimeProfile.OFFLINE,
        components=_components(),
    )

    assert status.schema_version == "1.1.0"
    assert status.checked_at == CHECKED_AT
    assert status.profile is RuntimeProfile.OFFLINE
    assert status.state is HealthState.DEGRADED
    assert status.components == _components()


def test_build_system_status_uses_most_severe_component_state() -> None:
    status = build_system_status(
        clock=lambda: CHECKED_AT,
        profile=RuntimeProfile.OFFLINE,
        components=_components(database=BLOCKED),
    )

    assert status.state is HealthState.BLOCKED
    assert status.components == _components(database=BLOCKED)


def test_build_system_status_rejects_an_empty_component_set() -> None:
    with pytest.raises(ValueError, match="at least one component"):
        build_system_status(
            clock=lambda: CHECKED_AT,
            profile=RuntimeProfile.OFFLINE,
            components=(),
        )
