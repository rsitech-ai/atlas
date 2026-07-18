import asyncio
import copy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from rsi_atlas_contracts.models import ResourceClass, ThermalState
from rsi_atlas_models.resource_arbiter import (
    InvalidResourceLeaseError,
    ResourceArbiter,
    ResourceLease,
    ResourcePolicy,
    ResourceRejectedError,
    ResourceRejectionCode,
    ResourceSnapshot,
)

NOW = datetime(2026, 7, 18, 18, 0, tzinfo=UTC)


def policy(*, max_light_leases: int = 2) -> ResourcePolicy:
    return ResourcePolicy(
        min_free_bytes=4_000,
        max_swap_bytes=1_000,
        allowed_thermal=frozenset({ThermalState.NOMINAL, ThermalState.FAIR}),
        max_snapshot_age=timedelta(seconds=30),
        max_light_leases=max_light_leases,
    )


def snapshot(**changes: object) -> ResourceSnapshot:
    values: dict[str, object] = {
        "free_bytes": 8_000,
        "swap_bytes": 100,
        "thermal": ThermalState.NOMINAL,
        "captured_at": NOW,
    }
    values.update(changes)
    return ResourceSnapshot(**values)  # type: ignore[arg-type]


def arbiter(*, max_light_leases: int = 2) -> ResourceArbiter:
    return ResourceArbiter(policy(max_light_leases=max_light_leases), clock=lambda: NOW)


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"captured_at": NOW + timedelta(microseconds=1)}, ResourceRejectionCode.SNAPSHOT_FUTURE),
        ({"captured_at": NOW - timedelta(seconds=31)}, ResourceRejectionCode.SNAPSHOT_STALE),
        ({"free_bytes": 3_999}, ResourceRejectionCode.FREE_MEMORY_LOW),
        ({"swap_bytes": 1_001}, ResourceRejectionCode.SWAP_HIGH),
        ({"thermal": ThermalState.SERIOUS}, ResourceRejectionCode.THERMAL_UNSAFE),
    ],
)
def test_unsafe_snapshot_rejections_are_exact_and_do_not_consume_capacity(
    changes: dict[str, object],
    code: ResourceRejectionCode,
) -> None:
    resource_arbiter = arbiter()
    with pytest.raises(ResourceRejectedError) as error:
        resource_arbiter.acquire(uuid4(), ResourceClass.HEAVY_MODEL, snapshot(**changes))
    assert error.value.code is code

    lease = resource_arbiter.acquire(uuid4(), ResourceClass.HEAVY_MODEL, snapshot())
    assert lease.is_active
    lease.release()


@pytest.mark.parametrize(
    "invalid_policy",
    [
        lambda: ResourcePolicy(-1, 1, frozenset({ThermalState.NOMINAL}), timedelta(seconds=1)),
        lambda: ResourcePolicy(1, -1, frozenset({ThermalState.NOMINAL}), timedelta(seconds=1)),
        lambda: ResourcePolicy(1, 1, frozenset(), timedelta(seconds=1)),
        lambda: ResourcePolicy(1, 1, frozenset({ThermalState.NOMINAL}), timedelta(0)),
        lambda: ResourcePolicy(1, 1, frozenset({ThermalState.NOMINAL}), timedelta(hours=2)),
        lambda: ResourcePolicy(1, 1, frozenset({ThermalState.NOMINAL}), timedelta(seconds=1), 0),
    ],
)
def test_policy_rejects_invalid_or_unbounded_values(invalid_policy: object) -> None:
    with pytest.raises(ValueError):
        invalid_policy()  # type: ignore[operator]


def test_snapshot_and_policy_are_frozen_and_strict() -> None:
    current = snapshot()
    current_policy = policy()
    with pytest.raises(FrozenInstanceError):
        current.free_bytes = 1  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        current_policy.max_swap_bytes = 2  # type: ignore[misc]
    with pytest.raises(ValueError):
        ResourceSnapshot(True, 0, ThermalState.NOMINAL, NOW)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ResourceSnapshot(1, 0, "nominal", NOW)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        ResourceSnapshot(1, 0, ThermalState.NOMINAL, datetime(2026, 7, 18))


def test_exactly_one_concurrent_heavy_lease_is_admitted() -> None:
    resource_arbiter = arbiter()

    def acquire_one(_: int) -> ResourceLease | None:
        try:
            return resource_arbiter.acquire(uuid4(), ResourceClass.HEAVY_MODEL, snapshot())
        except ResourceRejectedError as error:
            assert error.code is ResourceRejectionCode.HEAVY_BUSY
            return None

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(acquire_one, range(100)))

    leases = [lease for lease in results if lease is not None]
    assert len(leases) == 1
    leases[0].release()
    resource_arbiter.acquire(uuid4(), ResourceClass.HEAVY_MODEL, snapshot()).release()


def test_light_capacity_is_explicit_and_independent_of_heavy_capacity() -> None:
    resource_arbiter = arbiter(max_light_leases=2)
    heavy = resource_arbiter.acquire(uuid4(), ResourceClass.HEAVY_MODEL, snapshot())
    first = resource_arbiter.acquire(uuid4(), ResourceClass.LIGHT, snapshot())
    second = resource_arbiter.acquire(uuid4(), ResourceClass.LIGHT, snapshot())

    with pytest.raises(ResourceRejectedError) as error:
        resource_arbiter.acquire(uuid4(), ResourceClass.LIGHT, snapshot())
    assert error.value.code is ResourceRejectionCode.LIGHT_CAPACITY

    first.release()
    resource_arbiter.acquire(uuid4(), ResourceClass.LIGHT, snapshot()).release()
    second.release()
    heavy.release()


def test_context_exception_and_cancellation_release_capacity() -> None:
    resource_arbiter = arbiter()
    with (
        pytest.raises(RuntimeError),
        resource_arbiter.acquire(uuid4(), ResourceClass.HEAVY_MODEL, snapshot()),
    ):
        raise RuntimeError("fixture")
    with (
        pytest.raises(asyncio.CancelledError),
        resource_arbiter.acquire(uuid4(), ResourceClass.HEAVY_MODEL, snapshot()),
    ):
        raise asyncio.CancelledError
    resource_arbiter.acquire(uuid4(), ResourceClass.HEAVY_MODEL, snapshot()).release()


def test_release_is_idempotent_and_copy_or_forgery_cannot_change_capacity() -> None:
    first_arbiter = arbiter()
    second_arbiter = arbiter()
    lease = first_arbiter.acquire(uuid4(), ResourceClass.HEAVY_MODEL, snapshot())

    with pytest.raises(InvalidResourceLeaseError):
        copy.copy(lease)
    with pytest.raises(InvalidResourceLeaseError):
        copy.deepcopy(lease)
    with pytest.raises(InvalidResourceLeaseError):
        ResourceLease(first_arbiter, UUID(int=1), factory=object())
    with pytest.raises(InvalidResourceLeaseError):
        second_arbiter._release(lease)
    with pytest.raises(ResourceRejectedError) as busy:
        first_arbiter.acquire(uuid4(), ResourceClass.HEAVY_MODEL, snapshot())
    assert busy.value.code is ResourceRejectionCode.HEAVY_BUSY

    lease.release()
    lease.release()
    first_arbiter.acquire(uuid4(), ResourceClass.HEAVY_MODEL, snapshot()).release()


def test_invalid_boundary_input_fails_before_state_mutation() -> None:
    resource_arbiter = arbiter()
    with pytest.raises(ResourceRejectedError) as error:
        resource_arbiter.acquire("job", ResourceClass.HEAVY_MODEL, snapshot())  # type: ignore[arg-type]
    assert error.value.code is ResourceRejectionCode.INVALID_REQUEST
    resource_arbiter.acquire(uuid4(), ResourceClass.HEAVY_MODEL, snapshot()).release()
