"""Fail-closed analytics backend stubs without new dependencies."""

from __future__ import annotations

from rsi_atlas_contracts import (
    DEVELOPMENT_ANALYTICS_GATES,
    AnalyticsBackend,
    AnalyticsBackendGate,
)

from rsi_atlas_collectors.errors import AnalyticsBackendBlocked


def analytics_gates() -> tuple[AnalyticsBackendGate, ...]:
    return DEVELOPMENT_ANALYTICS_GATES


def require_postgres_only(backend: AnalyticsBackend) -> None:
    if backend in {AnalyticsBackend.DUCKDB, AnalyticsBackend.PARQUET}:
        raise AnalyticsBackendBlocked(
            f"{backend.value} remains blocked_dependency without governance approval"
        )
