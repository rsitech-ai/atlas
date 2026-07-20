"""Loopback collector and observation API contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from rsi_atlas_collectors import FixtureImportResult, import_fixture
from rsi_atlas_contracts import (
    ArtifactCommandContext,
    Observation,
    ProviderQualityState,
    SafeModeCapability,
)
from rsi_atlas_engine.api import create_app
from rsi_atlas_engine.collectors import CollectorServices
from rsi_atlas_engine.phase6 import Phase6Service
from rsi_atlas_recovery import SafeModeBlocked, SafeModeController, SafeModeStore
from rsi_atlas_security.ipc import ensure_ipc_token

TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000002")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000000003")
TRACE_ID = UUID("00000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def _headers() -> dict[str, str]:
    return {
        "x-rsi-tenant-id": str(TENANT_ID),
        "x-rsi-actor-id": str(ACTOR_ID),
        "x-rsi-trace-id": str(TRACE_ID),
    }


def _context() -> ArtifactCommandContext:
    return ArtifactCommandContext(
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        trace_id=TRACE_ID,
    )


class FakeCollectorService:
    def __init__(self) -> None:
        self._observations: dict[str, Observation] = {}

    def import_fixture(
        self,
        *,
        context: ArtifactCommandContext,
        fixture_name: str,
        provider_quality: ProviderQualityState = ProviderQualityState.SINGLE_SOURCE,
    ) -> FixtureImportResult:
        result = import_fixture(
            context=context,
            fixture_name=fixture_name,
            now=NOW,
            provider_quality=provider_quality,
        )
        if result.observation is not None:
            self._observations[result.observation.header.observation_id] = result.observation
        return result

    def list_observations(
        self,
        *,
        context: ArtifactCommandContext,
        as_of: datetime,
        subject_id: str | None = None,
    ) -> list[Observation]:
        del context
        items = [
            observation
            for observation in self._observations.values()
            if observation.header.available_time <= as_of
        ]
        if subject_id is not None:
            items = [
                observation for observation in items if subject_id in observation.header.subject_ids
            ]
        return items

    def get_observation(
        self, *, context: ArtifactCommandContext, observation_id: str
    ) -> Observation | None:
        del context
        return self._observations.get(observation_id)


def test_default_collector_service_rechecks_safe_mode_before_mutations(
    tmp_path: Path,
) -> None:
    store = SafeModeStore(tmp_path / "runtime")
    controller = SafeModeController(store)
    controller.require(SafeModeCapability.COLLECTORS)
    repository = Mock()
    collectors = CollectorServices(repository=repository, safe_mode=controller)
    SafeModeController(store).enter(reason="transitioned after route guard", entered_at=NOW)

    with pytest.raises(SafeModeBlocked, match="collectors"):
        collectors.import_fixture(
            context=_context(),
            fixture_name="bitcoin_block.json",
        )
    with pytest.raises(SafeModeBlocked, match="collectors"):
        collectors.orphan_observation(
            context=_context(),
            observation_id="obs_btc_block_840000",
        )

    repository.save_envelope.assert_not_called()
    repository.get_observation.assert_not_called()


def test_import_fixture_and_list_observations() -> None:
    client = TestClient(create_app(collector_service=FakeCollectorService()))
    response = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/collectors:import-fixture",
        headers=_headers(),
        json={"fixture_name": "bitcoin_block.json"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["envelope"]["source_family"] == "bitcoin"
    assert body["observation"]["header"]["source_family"] == "bitcoin"
    assert body["quarantine"] is None

    listed = client.get(
        f"/v1/workspaces/{WORKSPACE_ID}/observations",
        headers=_headers(),
        params={"as_of": "2026-07-19T12:00:00Z", "subject_id": "asset:btc"},
    )
    assert listed.status_code == 200
    assert len(listed.json()["observations"]) == 1


def test_conflicted_import_returns_quarantine() -> None:
    client = TestClient(create_app(collector_service=FakeCollectorService()))
    response = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/collectors:import-fixture",
        headers=_headers(),
        json={
            "fixture_name": "evm_block.json",
            "provider_quality": "conflicted",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["observation"] is None
    assert body["quarantine"]["reasons"] == ["provider_disagreement_conflicted"]


def test_invalid_fixture_is_a_client_error() -> None:
    client = TestClient(create_app(collector_service=FakeCollectorService()))

    response = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/collectors:import-fixture",
        headers=_headers(),
        json={"fixture_name": "missing.json"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Fixture import is invalid."}


def test_default_create_app_auto_wires_collectors() -> None:
    """Omitting collector_service still wires CollectorServices from the local DB.

    With Postgres available this returns 200; without it the route fail-closes as 503
    (no remote fallback). Explicit None→503 is not the product contract anymore.
    """
    client = TestClient(create_app())
    response = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/collectors:import-fixture",
        headers=_headers(),
        json={"fixture_name": "bitcoin_block.json"},
    )
    assert response.status_code in {200, 503}
    if response.status_code == 200:
        body = response.json()
        assert body["envelope"] is not None
        assert body["observation"] is not None or body["quarantine"] is not None


def test_safe_mode_blocks_collector_mutation_but_keeps_observations_readable(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RSI_ATLAS_DATA_ROOT", str(tmp_path / "runtime"))
    collectors = FakeCollectorService()
    client = TestClient(
        create_app(
            status_factory=lambda: (_ for _ in ()).throw(RuntimeError("unused")),
            collector_service=collectors,
        )
    )
    assert (
        client.post("/v1/recovery/safe-mode:enter", json={"reason": "operator"}).status_code == 200
    )

    blocked = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/collectors:import-fixture",
        headers=_headers(),
        json={"fixture_name": "bitcoin_block.json"},
    )
    assert blocked.status_code == 423
    assert blocked.json() == {"detail": "Safe Mode blocks collectors."}

    listed = client.get(
        f"/v1/workspaces/{WORKSPACE_ID}/observations",
        headers=_headers(),
        params={"as_of": "2026-07-19T12:00:00Z"},
    )
    assert listed.status_code == 200
    assert listed.json() == {"observations": []}


def test_injected_phase6_service_cannot_bypass_persisted_safe_mode(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "runtime"
    monkeypatch.setenv("RSI_ATLAS_DATA_ROOT", str(data_root))
    data_root.mkdir(mode=0o700)
    token = ensure_ipc_token(data_root / "ipc" / "engine.token")
    durable = SafeModeController(SafeModeStore(data_root))
    durable.enter(reason="persisted", entered_at=NOW)
    collectors = FakeCollectorService()
    client = TestClient(
        create_app(
            status_factory=lambda: (_ for _ in ()).throw(RuntimeError("unused")),
            collector_service=collectors,
            phase6_service=Phase6Service(safe_mode=SafeModeController()),
        )
    )

    current = client.get("/v1/recovery/safe-mode")
    assert current.status_code == 200
    assert current.json()["active"] is True
    blocked = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/collectors:import-fixture",
        headers=_headers(),
        json={"fixture_name": "bitcoin_block.json"},
    )
    assert blocked.status_code == 423
    assert blocked.json() == {"detail": "Safe Mode blocks collectors."}
    assert collectors._observations == {}

    exited = client.post(
        "/v1/recovery/safe-mode:exit",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert exited.status_code == 200
    assert exited.json()["active"] is False
    assert SafeModeController(SafeModeStore(data_root)).state.active is False
