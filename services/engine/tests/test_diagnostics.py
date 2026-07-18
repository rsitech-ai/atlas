from datetime import UTC, datetime

import pytest
from rsi_atlas_contracts.system_status import ComponentStatus, HealthState, RuntimeProfile
from rsi_atlas_engine.diagnostics import build_system_status

CHECKED_AT = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
DEGRADED = ComponentStatus(
    component_id="retrieval_index",
    title="Retrieval Index",
    state=HealthState.DEGRADED,
    summary="The optional retrieval index is rebuilding.",
)
BLOCKED = ComponentStatus(
    component_id="artifact_store",
    title="Artifact Store",
    state=HealthState.BLOCKED,
    summary="The artifact store is not available.",
)


def test_build_system_status_defaults_to_healthy_offline_foundation() -> None:
    status = build_system_status(clock=lambda: CHECKED_AT)

    assert status.checked_at == CHECKED_AT
    assert status.profile is RuntimeProfile.OFFLINE
    assert status.state is HealthState.HEALTHY
    assert [component.component_id for component in status.components] == [
        "engine_runtime",
        "offline_policy",
        "contract_api",
    ]


def test_build_system_status_uses_most_severe_component_state() -> None:
    status = build_system_status(clock=lambda: CHECKED_AT, components=(DEGRADED, BLOCKED))

    assert status.state is HealthState.BLOCKED
    assert status.components == (DEGRADED, BLOCKED)


def test_build_system_status_rejects_an_empty_component_set() -> None:
    with pytest.raises(ValueError, match="at least one component"):
        build_system_status(clock=lambda: CHECKED_AT, components=())
