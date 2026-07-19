"""Optional DuckDB / Parquet analytics under owner-private paths."""

from __future__ import annotations

import os
from pathlib import Path

from rsi_atlas_contracts import (
    AnalyticsBackend,
    AnalyticsBackendGate,
    AnalyticsBackendStatus,
)

from rsi_atlas_collectors.errors import AnalyticsBackendBlocked

try:
    import duckdb as _duckdb  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dependency
    _duckdb = None


def duckdb_enabled() -> bool:
    return os.environ.get("RSI_ATLAS_ENABLE_DUCKDB", "").strip() == "1" and _duckdb is not None


def analytics_gates() -> tuple[AnalyticsBackendGate, ...]:
    if duckdb_enabled():
        return (
            AnalyticsBackendGate(
                backend=AnalyticsBackend.POSTGRES,
                status=AnalyticsBackendStatus.AVAILABLE,
                reason="postgresql stores operational normalized observations",
            ),
            AnalyticsBackendGate(
                backend=AnalyticsBackend.DUCKDB,
                status=AnalyticsBackendStatus.AVAILABLE,
                reason="optional local duckdb analytics enabled by RSI_ATLAS_ENABLE_DUCKDB=1",
            ),
            AnalyticsBackendGate(
                backend=AnalyticsBackend.PARQUET,
                status=AnalyticsBackendStatus.AVAILABLE,
                reason="parquet export via duckdb under owner-private root",
            ),
        )
    return (
        AnalyticsBackendGate(
            backend=AnalyticsBackend.POSTGRES,
            status=AnalyticsBackendStatus.AVAILABLE,
            reason="postgresql stores operational normalized observations",
        ),
        AnalyticsBackendGate(
            backend=AnalyticsBackend.DUCKDB,
            status=AnalyticsBackendStatus.BLOCKED_DEPENDENCY,
            reason="set RSI_ATLAS_ENABLE_DUCKDB=1 and install duckdb optional extra",
        ),
        AnalyticsBackendGate(
            backend=AnalyticsBackend.PARQUET,
            status=AnalyticsBackendStatus.BLOCKED_DEPENDENCY,
            reason="parquet writers require duckdb optional path",
        ),
    )


def require_postgres_only(backend: AnalyticsBackend) -> None:
    """Fail closed unless optional DuckDB path is enabled and importable."""
    if backend is AnalyticsBackend.POSTGRES:
        return
    if backend in {AnalyticsBackend.DUCKDB, AnalyticsBackend.PARQUET} and duckdb_enabled():
        return
    raise AnalyticsBackendBlocked(
        f"{backend.value} remains blocked_dependency without RSI_ATLAS_ENABLE_DUCKDB=1 "
        "and duckdb install"
    )


def export_rows_to_parquet(
    *,
    rows: list[dict[str, object]],
    destination: Path,
) -> Path:
    """Write local Parquet via DuckDB. No network."""
    require_postgres_only(AnalyticsBackend.PARQUET)
    if _duckdb is None:
        raise AnalyticsBackendBlocked("duckdb import failed")
    if destination.suffix != ".parquet":
        raise AnalyticsBackendBlocked("destination must end with .parquet")
    destination.parent.mkdir(parents=True, exist_ok=True)
    connection = _duckdb.connect(database=":memory:")
    if not rows:
        connection.execute("CREATE TABLE export(placeholder VARCHAR)")
    else:
        columns = list(rows[0].keys())
        col_sql = ", ".join(f'"{name}" VARCHAR' for name in columns)
        connection.execute(f"CREATE TABLE export({col_sql})")
        for row in rows:
            values = [str(row.get(name, "")) for name in columns]
            placeholders = ", ".join("?" for _ in columns)
            connection.execute(f"INSERT INTO export VALUES ({placeholders})", values)
    # Escape single quotes in path for SQL literal
    path_sql = destination.as_posix().replace("'", "''")
    connection.execute(f"COPY export TO '{path_sql}' (FORMAT PARQUET)")
    connection.close()
    return destination


__all__ = [
    "analytics_gates",
    "duckdb_enabled",
    "export_rows_to_parquet",
    "require_postgres_only",
]
