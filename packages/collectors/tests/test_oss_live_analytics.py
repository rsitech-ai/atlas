"""Live collector policy + DuckDB gate tests."""

from __future__ import annotations

import os
from uuid import UUID

import pytest
from rsi_atlas_collectors import (
    LiveCollectorBlocked,
    analytics_gates,
    duckdb_enabled,
    refuse_live_collect,
    require_postgres_only,
)
from rsi_atlas_collectors.live_http import collect_live_json, live_collector_definition
from rsi_atlas_contracts import (
    AcquisitionMode,
    AnalyticsBackend,
    AnalyticsBackendStatus,
    ArtifactCommandContext,
    SourceFamily,
)
from rsi_atlas_security.network_policy import NetworkPolicy


def test_refuse_live_by_default() -> None:
    with pytest.raises(LiveCollectorBlocked, match="blocked_live_network"):
        refuse_live_collect(family=SourceFamily.EVM, mode=AcquisitionMode.ON_DEMAND)


def test_live_definition_requires_allowlist() -> None:
    definition = live_collector_definition(family=SourceFamily.EVM, origin="https://127.0.0.1:8545")
    assert definition.allowlist == ("https://127.0.0.1:8545",)
    assert definition.acquisition_mode is AcquisitionMode.ON_DEMAND


def test_offline_policy_denies_before_http() -> None:
    policy = NetworkPolicy.offline()
    context = ArtifactCommandContext(
        tenant_id=UUID("00000000-0000-4000-8000-000000000001"),
        workspace_id=UUID("00000000-0000-4000-8000-000000000002"),
        actor_id=UUID("00000000-0000-4000-8000-000000000003"),
        trace_id=UUID("00000000-0000-4000-8000-000000000004"),
    )
    with pytest.raises(LiveCollectorBlocked, match="deny_live"):
        collect_live_json(
            family=SourceFamily.EVM,
            mode=AcquisitionMode.ON_DEMAND,
            origin="https://127.0.0.1:8545",
            path="/",
            context=context,
            policy=policy,
        )


def test_analytics_gates_default_blocked() -> None:
    os.environ.pop("RSI_ATLAS_ENABLE_DUCKDB", None)
    gates = analytics_gates()
    duck = next(g for g in gates if g.backend is AnalyticsBackend.DUCKDB)
    assert duck.status is AnalyticsBackendStatus.BLOCKED_DEPENDENCY
    assert duckdb_enabled() is False
    with pytest.raises(Exception, match="blocked_dependency"):
        require_postgres_only(AnalyticsBackend.DUCKDB)
