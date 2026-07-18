"""Explicit, thread-safe admission for Phase 1 model resource leases."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import TracebackType
from typing import Self
from uuid import UUID, uuid4

from rsi_atlas_contracts.models import ResourceClass, ThermalState

_MAX_RESOURCE_BYTES = (1 << 63) - 1
_SAFE_THERMAL_STATES = frozenset({ThermalState.NOMINAL, ThermalState.FAIR})


class ResourceRejectionCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    SNAPSHOT_FUTURE = "snapshot_future"
    SNAPSHOT_STALE = "snapshot_stale"
    FREE_MEMORY_LOW = "free_memory_low"
    SWAP_HIGH = "swap_high"
    THERMAL_UNSAFE = "thermal_unsafe"
    HEAVY_BUSY = "heavy_resource_busy"
    LIGHT_CAPACITY = "light_capacity_exhausted"


class ResourceRejectedError(RuntimeError):
    def __init__(self, code: ResourceRejectionCode) -> None:
        self.code = code
        super().__init__(code.value)


class InvalidResourceLeaseError(RuntimeError):
    code = "invalid_resource_lease"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    free_bytes: int
    swap_bytes: int
    thermal: ThermalState
    captured_at: datetime

    def __post_init__(self) -> None:
        if (
            type(self.free_bytes) is not int
            or self.free_bytes < 0
            or self.free_bytes > _MAX_RESOURCE_BYTES
        ):
            raise ValueError("resource free bytes are invalid")
        if (
            type(self.swap_bytes) is not int
            or self.swap_bytes < 0
            or self.swap_bytes > _MAX_RESOURCE_BYTES
        ):
            raise ValueError("resource swap bytes are invalid")
        if type(self.thermal) is not ThermalState:
            raise ValueError("resource thermal state is invalid")
        if type(self.captured_at) is not datetime or self.captured_at.tzinfo is None:
            raise ValueError("resource capture time must be timezone-aware")
        if self.captured_at.utcoffset() is None:
            raise ValueError("resource capture time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ResourcePolicy:
    min_free_bytes: int
    max_swap_bytes: int
    allowed_thermal: frozenset[ThermalState]
    max_snapshot_age: timedelta
    max_light_leases: int = 8

    def __post_init__(self) -> None:
        if (
            type(self.min_free_bytes) is not int
            or self.min_free_bytes < 0
            or self.min_free_bytes > _MAX_RESOURCE_BYTES
        ):
            raise ValueError("minimum free bytes are invalid")
        if (
            type(self.max_swap_bytes) is not int
            or self.max_swap_bytes < 0
            or self.max_swap_bytes > _MAX_RESOURCE_BYTES
        ):
            raise ValueError("maximum swap bytes are invalid")
        if (
            type(self.allowed_thermal) is not frozenset
            or not self.allowed_thermal
            or any(type(state) is not ThermalState for state in self.allowed_thermal)
            or not self.allowed_thermal <= _SAFE_THERMAL_STATES
        ):
            raise ValueError("allowed thermal states are invalid")
        if (
            type(self.max_snapshot_age) is not timedelta
            or self.max_snapshot_age <= timedelta(0)
            or self.max_snapshot_age > timedelta(hours=1)
        ):
            raise ValueError("maximum snapshot age is invalid")
        if type(self.max_light_leases) is not int or not 1 <= self.max_light_leases <= 1_024:
            raise ValueError("maximum light leases are invalid")


_LEASE_FACTORY = object()


class ResourceLease:
    __slots__ = ("_arbiter", "_release_lock", "_released", "_token")

    def __init__(
        self,
        arbiter: ResourceArbiter,
        token: UUID,
        *,
        factory: object,
    ) -> None:
        if factory is not _LEASE_FACTORY:
            raise InvalidResourceLeaseError
        self._arbiter = arbiter
        self._token = token
        self._released = False
        self._release_lock = threading.Lock()

    @property
    def is_active(self) -> bool:
        with self._release_lock:
            return not self._released

    def release(self) -> None:
        with self._release_lock:
            if self._released:
                return
            self._arbiter._release(self)
            self._released = True

    def __enter__(self) -> Self:
        if not self.is_active:
            raise InvalidResourceLeaseError
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        self.release()

    def __copy__(self) -> ResourceLease:
        raise InvalidResourceLeaseError

    def __deepcopy__(self, memo: dict[int, object]) -> ResourceLease:
        del memo
        raise InvalidResourceLeaseError


@dataclass(frozen=True, slots=True)
class _ActiveLease:
    lease: ResourceLease
    job_id: UUID
    resource_class: ResourceClass


class ResourceArbiter:
    def __init__(
        self,
        policy: ResourcePolicy,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if type(policy) is not ResourcePolicy:
            raise ValueError("resource policy is required")
        self._policy = policy
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._active: dict[UUID, _ActiveLease] = {}

    def acquire(
        self,
        job_id: UUID,
        resource_class: ResourceClass,
        snapshot: ResourceSnapshot,
    ) -> ResourceLease:
        if (
            type(job_id) is not UUID
            or job_id.int == 0
            or type(resource_class) is not ResourceClass
            or type(snapshot) is not ResourceSnapshot
        ):
            raise ResourceRejectedError(ResourceRejectionCode.INVALID_REQUEST)
        now = self._clock()
        if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
            raise ResourceRejectedError(ResourceRejectionCode.INVALID_REQUEST)
        if snapshot.captured_at > now:
            raise ResourceRejectedError(ResourceRejectionCode.SNAPSHOT_FUTURE)
        if now - snapshot.captured_at > self._policy.max_snapshot_age:
            raise ResourceRejectedError(ResourceRejectionCode.SNAPSHOT_STALE)
        if snapshot.free_bytes < self._policy.min_free_bytes:
            raise ResourceRejectedError(ResourceRejectionCode.FREE_MEMORY_LOW)
        if snapshot.swap_bytes > self._policy.max_swap_bytes:
            raise ResourceRejectedError(ResourceRejectionCode.SWAP_HIGH)
        if snapshot.thermal not in self._policy.allowed_thermal:
            raise ResourceRejectedError(ResourceRejectionCode.THERMAL_UNSAFE)

        with self._lock:
            active = tuple(self._active.values())
            if resource_class is ResourceClass.HEAVY_MODEL and any(
                item.resource_class is ResourceClass.HEAVY_MODEL for item in active
            ):
                raise ResourceRejectedError(ResourceRejectionCode.HEAVY_BUSY)
            if (
                resource_class is ResourceClass.LIGHT
                and sum(item.resource_class is ResourceClass.LIGHT for item in active)
                >= self._policy.max_light_leases
            ):
                raise ResourceRejectedError(ResourceRejectionCode.LIGHT_CAPACITY)
            token = uuid4()
            lease = ResourceLease(self, token, factory=_LEASE_FACTORY)
            self._active[token] = _ActiveLease(lease, job_id, resource_class)
            return lease

    def _release(self, lease: ResourceLease) -> None:
        with self._lock:
            active = self._active.get(lease._token)
            if active is None or active.lease is not lease:
                raise InvalidResourceLeaseError
            del self._active[lease._token]


__all__ = [
    "InvalidResourceLeaseError",
    "ResourceArbiter",
    "ResourceLease",
    "ResourcePolicy",
    "ResourceRejectedError",
    "ResourceRejectionCode",
    "ResourceSnapshot",
]
