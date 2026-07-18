from pathlib import Path

from fastapi.testclient import TestClient
from rsi_atlas_contracts import HealthState, SystemStatus
from rsi_atlas_engine.api import create_app


def _fixture_status() -> SystemStatus:
    root = Path(__file__).resolve().parents[3]
    fixture = root / "apps/macos/Tests/RSIAtlasCoreTests/Fixtures/system_status_v1_1.json"
    return SystemStatus.model_validate_json(fixture.read_text())


def test_system_status_endpoint_returns_the_versioned_runtime_contract() -> None:
    expected = _fixture_status()
    client = TestClient(create_app(status_factory=lambda: expected))

    response = client.get("/v1/system/status")

    assert response.status_code == 200
    assert response.json() == expected.model_dump(mode="json")
    assert len(response.json()["components"]) == 8


def test_system_status_endpoint_keeps_diagnostic_contract_reachable_when_blocked() -> None:
    baseline = _fixture_status()
    blocked_component = baseline.components[1].model_copy(
        update={
            "state": HealthState.BLOCKED,
            "summary": "PostgreSQL is unavailable.",
            "remediation": "Start the project-owned PostgreSQL runtime, then refresh.",
        }
    )
    blocked = baseline.model_copy(
        update={
            "state": HealthState.BLOCKED,
            "components": (
                baseline.components[0],
                blocked_component,
                *baseline.components[2:],
            ),
        }
    )
    client = TestClient(create_app(status_factory=lambda: blocked))

    response = client.get("/v1/system/status")

    assert response.status_code == 200
    assert response.json()["state"] == "blocked"
    assert response.json()["components"][1]["remediation"].startswith("Start")
