"""Local model runtime tests."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from rsi_atlas_contracts.models import ThermalState
from rsi_atlas_models.local_runtime import (
    LocalModelBackend,
    LocalModelError,
    default_local_runtime,
)
from rsi_atlas_models.resource_arbiter import ResourceSnapshot


def _snap(*, free: int = 2 * 1024**3) -> ResourceSnapshot:
    return ResourceSnapshot(
        free_bytes=free,
        swap_bytes=0,
        thermal=ThermalState.NOMINAL,
        captured_at=datetime.now(tz=UTC),
    )


def test_foundation_models_unavailable() -> None:
    runtime = default_local_runtime()
    with pytest.raises(LocalModelError, match="apple_foundation_models unavailable"):
        runtime.load(
            model_id="afm",
            backend=LocalModelBackend.APPLE_FOUNDATION_MODELS,
            snapshot=_snap(),
        )


def test_load_unload_token_hash() -> None:
    runtime = default_local_runtime()
    handle = runtime.load(
        model_id="oss_token_hash_v1",
        backend=LocalModelBackend.TOKEN_HASH,
        snapshot=_snap(),
        job_id=uuid4(),
    )
    assert handle.backend is LocalModelBackend.TOKEN_HASH
    assert "oss_token_hash_v1" in runtime.loaded_ids()
    runtime.unload("oss_token_hash_v1")
    assert runtime.loaded_ids() == ()


def test_oom_recovery_unloads() -> None:
    runtime = default_local_runtime()
    runtime.load(
        model_id="a",
        backend=LocalModelBackend.TOKEN_HASH,
        snapshot=_snap(),
    )
    with pytest.raises(LocalModelError, match="oom_or_pressure"):
        runtime.load(
            model_id="b",
            backend=LocalModelBackend.ONNX,
            snapshot=_snap(free=1),
        )
    assert runtime.loaded_ids() == ()
