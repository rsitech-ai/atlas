import math
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from rsi_atlas_contracts.models import ResourceClass, ThermalState


class ResourceRejectedError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResourceSnapshot:
    free_bytes: int
    swap_bytes: int
    thermal: ThermalState
    captured_at: datetime

    def __post_init__(self) -> None:
        if (
            self.free_bytes < 0
            or self.swap_bytes < 0
            or not math.isfinite(self.free_bytes + self.swap_bytes)
        ):
            raise ValueError("invalid resource snapshot")


@dataclass(frozen=True)
class ResourcePolicy:
    min_free_bytes: int
    max_swap_bytes: int
    allowed_thermal: frozenset[ThermalState]
    max_snapshot_age: timedelta

    def __post_init__(self) -> None:
        if (
            self.min_free_bytes < 0
            or self.max_swap_bytes < 0
            or not self.allowed_thermal
            or self.max_snapshot_age.total_seconds() <= 0
        ):
            raise ValueError("invalid resource policy")


class ResourceLease:
    def __init__(self, arbiter: "ResourceArbiter", token: UUID) -> None:
        self._arbiter = arbiter
        self._token = token
        self._released = False

    def release(self) -> None:
        if not self._released:
            self._arbiter._release(self._token)
            self._released = True

    def __enter__(self) -> "ResourceLease":
        return self

    def __exit__(self, *args: object) -> None:
        self.release()


class ResourceArbiter:
    def __init__(self, policy: ResourcePolicy) -> None:
        self._policy = policy
        self._lock = threading.Lock()
        self._heavy: UUID | None = None

    def acquire(
        self, job_id: UUID, resource: ResourceClass, snapshot: ResourceSnapshot
    ) -> ResourceLease:
        now = datetime.now(UTC)
        if (
            snapshot.captured_at.tzinfo is None
            or snapshot.captured_at > now
            or now - snapshot.captured_at > self._policy.max_snapshot_age
            or snapshot.free_bytes < self._policy.min_free_bytes
            or snapshot.swap_bytes > self._policy.max_swap_bytes
            or snapshot.thermal not in self._policy.allowed_thermal
        ):
            raise ResourceRejectedError("unsafe resource snapshot")
        with self._lock:
            if resource is ResourceClass.HEAVY_MODEL and self._heavy is not None:
                raise ResourceRejectedError("heavy resource busy")
            token = uuid4()
            if resource is ResourceClass.HEAVY_MODEL:
                self._heavy = token
            return ResourceLease(self, token)

    def _release(self, token: UUID) -> None:
        with self._lock:
            if self._heavy == token:
                self._heavy = None
