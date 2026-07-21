"""Authenticated UDS server composition over the bundled PostgreSQL lifecycle."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import uvicorn
from rsi_atlas_security.ipc import (
    IpcTransportMode,
    assert_no_unintended_tcp,
    ensure_ipc_token,
    prepare_uds_path,
    resolve_ipc_bind,
)

from rsi_atlas_engine.embedded_postgres import EmbeddedPostgres
from rsi_atlas_engine.runtime import RuntimePaths


class PostgresLifecycle(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


def _postgres_factory(runtime_root: Path, data_root: Path) -> PostgresLifecycle:
    return EmbeddedPostgres(runtime_root=runtime_root, data_root=data_root)


def serve_release(
    *,
    postgres_factory: Callable[[Path, Path], PostgresLifecycle] = _postgres_factory,
    uvicorn_runner: Callable[..., object] = uvicorn.run,
) -> int:
    """Run the self-contained release engine and stop its database on every exit path."""
    os.environ["RSI_ATLAS_RELEASE_IPC"] = "1"
    os.environ["RSI_ATLAS_IPC_AUTH"] = "1"
    os.environ.pop("RSI_ATLAS_ALLOW_LOOPBACK_TCP", None)
    raw_runtime_root = os.environ.get("RSI_ATLAS_RUNTIME_ROOT", "")
    runtime_root = Path(raw_runtime_root)
    if not raw_runtime_root or not runtime_root.is_absolute():
        raise ValueError("embedded runtime root is not configured")
    runtime_root = runtime_root.resolve(strict=True)
    paths = RuntimePaths.from_environment()
    postgres = postgres_factory(runtime_root, paths.data_root)
    postgres.start()
    try:
        config = resolve_ipc_bind(data_root=paths.data_root)
        assert_no_unintended_tcp(release_mode=True, mode=config.mode)
        if config.mode is not IpcTransportMode.UNIX_DOMAIN or config.uds_path is None:
            raise RuntimeError("release engine requires Unix-domain IPC")
        ensure_ipc_token(config.token_path)
        uds_path = prepare_uds_path(config.uds_path)
        uvicorn_runner(
            "rsi_atlas_engine.api:app",
            uds=str(uds_path),
            factory=False,
            log_level="info",
        )
    finally:
        postgres.stop()
    return 0


__all__ = ["serve_release"]
