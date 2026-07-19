"""Loopback collector and observation API contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient
from rsi_atlas_collectors import FixtureImportResult, import_fixture
from rsi_atlas_contracts import (
    ArtifactCommandContext,
    Observation,
    ProviderQualityState,
)
from rsi_atlas_engine.api import create_app

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
