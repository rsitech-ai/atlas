"""Local model load/unload with OOM-style recovery and Foundation Models honesty."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from threading import Lock
from uuid import UUID, uuid4

from rsi_atlas_contracts.models import ResourceClass, ThermalState

from rsi_atlas_models.resource_arbiter import (
    ResourceArbiter,
    ResourceLease,
    ResourcePolicy,
    ResourceRejectedError,
    ResourceRejectionCode,
    ResourceSnapshot,
)


class LocalModelBackend(StrEnum):
    ONNX = "onnx"
    TOKEN_HASH = "token_hash"
    APPLE_FOUNDATION_MODELS = "apple_foundation_models"


class LocalModelError(RuntimeError):
    """Raised when local model lifecycle fails closed."""


@dataclass(frozen=True, slots=True)
class LocalModelHandle:
    model_id: str
    backend: LocalModelBackend
    dimensions: int


@dataclass
class LocalModelRuntime:
    """Load/unload local embedders under the resource arbiter.

    Apple Foundation Models: honest unavailable until SDK wiring exists.
    """

    arbiter: ResourceArbiter
    _lock: Lock = field(default_factory=Lock)
    _loaded: dict[str, tuple[LocalModelHandle, ResourceLease]] = field(default_factory=dict)

    def load(
        self,
        *,
        model_id: str,
        backend: LocalModelBackend,
        snapshot: ResourceSnapshot,
        dimensions: int = 64,
        job_id: UUID | None = None,
    ) -> LocalModelHandle:
        if backend is LocalModelBackend.APPLE_FOUNDATION_MODELS:
            raise LocalModelError(
                "apple_foundation_models unavailable: SDK integration not present on this build"
            )
        with self._lock:
            if model_id in self._loaded:
                return self._loaded[model_id][0]
            try:
                lease = self.arbiter.acquire(
                    job_id or uuid4(),
                    ResourceClass.HEAVY_MODEL
                    if backend is LocalModelBackend.ONNX
                    else ResourceClass.LIGHT,
                    snapshot,
                )
            except ResourceRejectedError as exc:
                if exc.code in {
                    ResourceRejectionCode.FREE_MEMORY_LOW,
                    ResourceRejectionCode.SWAP_HIGH,
                    ResourceRejectionCode.HEAVY_BUSY,
                }:
                    self._unload_all_unlocked()
                    raise LocalModelError(f"oom_or_pressure:{exc.code.value}") from exc
                raise LocalModelError(exc.code.value) from exc
            handle = LocalModelHandle(
                model_id=model_id,
                backend=backend,
                dimensions=dimensions,
            )
            self._loaded[model_id] = (handle, lease)
            return handle

    def unload(self, model_id: str) -> None:
        with self._lock:
            pair = self._loaded.pop(model_id, None)
            if pair is None:
                return
            _handle, lease = pair
            lease.release()

    def recover_oom(self) -> tuple[str, ...]:
        """Unload all models to reclaim memory (fail-soft recovery)."""
        with self._lock:
            return self._unload_all_unlocked()

    def _unload_all_unlocked(self) -> tuple[str, ...]:
        unloaded: list[str] = []
        for model_id, (_handle, lease) in list(self._loaded.items()):
            lease.release()
            unloaded.append(model_id)
            del self._loaded[model_id]
        return tuple(unloaded)

    def loaded_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._loaded))


def default_local_runtime() -> LocalModelRuntime:
    policy = ResourcePolicy(
        min_free_bytes=512 * 1024 * 1024,
        max_swap_bytes=2 * 1024 * 1024 * 1024,
        allowed_thermal=frozenset({ThermalState.NOMINAL, ThermalState.FAIR}),
        max_snapshot_age=timedelta(seconds=30),
        max_light_leases=8,
    )
    return LocalModelRuntime(arbiter=ResourceArbiter(policy))


__all__ = [
    "LocalModelBackend",
    "LocalModelError",
    "LocalModelHandle",
    "LocalModelRuntime",
    "default_local_runtime",
]
