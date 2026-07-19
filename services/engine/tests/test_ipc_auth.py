"""Engine IPC auth middleware tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from rsi_atlas_contracts import SystemStatus
from rsi_atlas_engine.api import create_app
from rsi_atlas_security.ipc import ensure_ipc_token


def _fixture_status() -> SystemStatus:
    root = Path(__file__).resolve().parents[3]
    fixture = root / "apps/macos/Tests/RSIAtlasCoreTests/Fixtures/system_status_v1_1.json"
    return SystemStatus.model_validate_json(fixture.read_text())


def test_ipc_auth_rejects_missing_token(tmp_path: Path) -> None:
    token_path = tmp_path / "engine.token"
    ensure_ipc_token(token_path)
    client = TestClient(
        create_app(
            status_factory=_fixture_status,
            require_ipc_auth=True,
            ipc_token_path=token_path,
        )
    )
    response = client.get("/v1/system/status")
    assert response.status_code == 401


def test_ipc_auth_accepts_bearer(tmp_path: Path) -> None:
    token_path = tmp_path / "engine.token"
    token = ensure_ipc_token(token_path)
    client = TestClient(
        create_app(
            status_factory=_fixture_status,
            require_ipc_auth=True,
            ipc_token_path=token_path,
        )
    )
    response = client.get(
        "/v1/system/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == _fixture_status().model_dump(mode="json")


def test_ipc_auth_disabled_by_default() -> None:
    client = TestClient(create_app(status_factory=_fixture_status))
    response = client.get("/v1/system/status")
    assert response.status_code == 200
