from datetime import UTC, datetime

from fastapi.testclient import TestClient
from rsi_atlas_contracts import ComponentStatus, HealthState, RuntimeProfile, SystemStatus
from rsi_atlas_engine.api import create_app

EXPECTED_STATUS = SystemStatus(
    schema_version="1.0.0",
    product="RSI Atlas Engine",
    profile=RuntimeProfile.OFFLINE,
    state=HealthState.HEALTHY,
    checked_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
    components=(
        ComponentStatus(
            component_id="engine_runtime",
            title="Engine Runtime",
            state=HealthState.HEALTHY,
            summary="The local engine can evaluate foundation diagnostics.",
        ),
    ),
)


def test_system_status_endpoint_returns_the_versioned_contract() -> None:
    client = TestClient(create_app(status_factory=lambda: EXPECTED_STATUS))

    response = client.get("/v1/system/status")

    assert response.status_code == 200
    assert response.json() == EXPECTED_STATUS.model_dump(mode="json")
