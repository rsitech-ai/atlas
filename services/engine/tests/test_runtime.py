from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic

import pytest
import rsi_atlas_engine.runtime as runtime_module
from rsi_atlas_contracts import ComponentGroup, HealthState, ThermalState
from rsi_atlas_engine.runtime import (
    COMPONENT_IDS,
    RUNTIME_SENTINEL_BYTES,
    RUNTIME_SENTINEL_ID,
    MacResourceSampler,
    ProbeObservation,
    RuntimePaths,
    RuntimeProbe,
    RuntimeServices,
)
from rsi_atlas_models import ResourceSnapshot
from rsi_atlas_storage import (
    ContentAddressedArtifactStore,
    DatabaseSettings,
    MigrationRunner,
    PostgresDatabase,
)

CHECKED_AT = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)


class SafeResourceSampler:
    def sample(self) -> ResourceSnapshot:
        return ResourceSnapshot(
            free_bytes=8 * 1024**3,
            swap_bytes=0,
            thermal=ThermalState.NOMINAL,
            captured_at=CHECKED_AT,
        )


class FixedResourceSampler:
    def __init__(self, captured_at: datetime) -> None:
        self._captured_at = captured_at

    def sample(self) -> ResourceSnapshot:
        return ResourceSnapshot(
            free_bytes=8 * 1024**3,
            swap_bytes=0,
            thermal=ThermalState.NOMINAL,
            captured_at=self._captured_at,
        )


def _probe(
    component_id: str,
    *,
    group: ComponentGroup = ComponentGroup.ENGINE,
    observation: ProbeObservation | None = None,
    check: Callable[[], ProbeObservation] | None = None,
) -> RuntimeProbe:
    result = observation or ProbeObservation(
        state=HealthState.HEALTHY,
        summary=f"{component_id} is healthy.",
    )
    return RuntimeProbe(
        component_id=component_id,
        title=component_id.replace("_", " ").title(),
        group=group,
        check=check or (lambda: result),
        failure_state=HealthState.BLOCKED,
        failure_summary=f"{component_id} check failed.",
        failure_remediation=f"Repair {component_id}.",
    )


def _eight_probes(*, replacement: RuntimeProbe | None = None) -> tuple[RuntimeProbe, ...]:
    groups = {
        "engine_runtime": ComponentGroup.ENGINE,
        "database": ComponentGroup.STORAGE,
        "artifact_store": ComponentGroup.STORAGE,
        "offline_policy": ComponentGroup.PRIVACY,
        "trace_store": ComponentGroup.OBSERVABILITY,
        "resource_policy": ComponentGroup.RESOURCES,
        "model_registry": ComponentGroup.RESOURCES,
        "contract_api": ComponentGroup.ENGINE,
    }
    return tuple(
        replacement
        if replacement is not None and replacement.component_id == component_id
        else _probe(component_id, group=groups[component_id])
        for component_id in COMPONENT_IDS
    )


def test_runtime_services_require_exact_ordered_runtime_probes() -> None:
    with pytest.raises(ValueError, match="exact runtime probes"):
        RuntimeServices(probes=(_probe("engine_runtime"),), clock=lambda: CHECKED_AT)

    services = RuntimeServices(probes=_eight_probes(), clock=lambda: CHECKED_AT)
    status = services.status()

    assert tuple(component.component_id for component in status.components) == COMPONENT_IDS
    assert status.checked_at == CHECKED_AT
    assert status.state is HealthState.HEALTHY


def test_model_unavailability_status_is_scoped_to_the_local_runtime() -> None:
    observation = runtime_module._check_model_registry()

    assert observation.summary == "No production-qualified local model or provider is active."
    assert observation.remediation == (
        "Select and admit a provider only after governed evaluation and owner approval."
    )
    assert "Phase 1" not in observation.summary


def test_probe_failure_is_sanitized_and_cannot_escape_status_contract() -> None:
    def fail() -> ProbeObservation:
        raise RuntimeError("secret=/private/research/raw-payload")

    failed = _probe("database", group=ComponentGroup.STORAGE, check=fail)
    status = RuntimeServices(
        probes=_eight_probes(replacement=failed),
        clock=lambda: CHECKED_AT,
    ).status()

    database = next(item for item in status.components if item.component_id == "database")
    assert database.state is HealthState.BLOCKED
    assert database.summary == "database check failed."
    assert database.remediation == "Repair database."
    assert "secret" not in status.model_dump_json()
    assert "/private" not in status.model_dump_json()


def test_malformed_probe_observation_is_contained_and_sanitized() -> None:
    malformed = _probe(
        "database",
        group=ComponentGroup.STORAGE,
        observation=ProbeObservation(
            state=HealthState.HEALTHY,
            summary="secret=/private/research\nraw-payload",
        ),
    )

    status = RuntimeServices(
        probes=_eight_probes(replacement=malformed),
        clock=lambda: CHECKED_AT,
    ).status()

    database = next(item for item in status.components if item.component_id == "database")
    assert database.state is HealthState.BLOCKED
    assert database.summary == "database check failed."
    assert database.remediation == "Repair database."
    assert "secret" not in status.model_dump_json()
    assert "/private" not in status.model_dump_json()


def test_mac_resource_sampler_returns_a_current_bounded_snapshot() -> None:
    before = datetime.now(UTC)
    snapshot = MacResourceSampler().sample()
    after = datetime.now(UTC)

    assert 0 <= snapshot.free_bytes < 1 << 63
    assert 0 <= snapshot.swap_bytes < 1 << 63
    assert snapshot.thermal in set(ThermalState)
    assert before <= snapshot.captured_at <= after


def test_invalid_data_root_returns_diagnostic_contract_instead_of_crashing(
    tmp_path: Path,
) -> None:
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o700)
    unsafe.chmod(0o755)

    status = RuntimeServices.from_environment(
        environ={"RSI_ATLAS_DATA_ROOT": str(unsafe)},
        clock=lambda: CHECKED_AT,
    ).status()

    assert tuple(component.component_id for component in status.components) == COMPONENT_IDS
    assert status.state is HealthState.UNSAFE
    offline = next(item for item in status.components if item.component_id == "offline_policy")
    assert offline.state is HealthState.UNSAFE
    assert str(unsafe) not in status.model_dump_json()


def test_missing_data_root_is_bootstrapped_owner_private(tmp_path: Path) -> None:
    data_root = tmp_path / "runtime"

    paths = RuntimePaths.from_data_root(data_root)

    assert paths.data_root == data_root
    assert data_root.is_dir()
    assert data_root.stat().st_mode & 0o777 == 0o700


def test_data_root_cannot_alias_read_only_resource_root(tmp_path: Path) -> None:
    resource_root = tmp_path / "resources"
    resource_root.mkdir(mode=0o700)
    (resource_root / "migrations").mkdir()

    with pytest.raises(ValueError, match="separate"):
        RuntimePaths.from_data_root(resource_root, repository_root=resource_root)

    nested_data = resource_root / "writable-data"
    with pytest.raises(ValueError, match="separate"):
        RuntimePaths.from_data_root(nested_data, repository_root=resource_root)
    assert not nested_data.exists()


def test_missing_data_root_rejects_symlinked_parent(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir(mode=0o700)
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    data_root = linked_parent / "runtime"

    with pytest.raises((OSError, ValueError)):
        RuntimePaths.from_data_root(data_root)

    assert not (real_parent / "runtime").exists()


def test_offline_policy_is_unsafe_when_exact_postgres_socket_is_absent(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "runtime"
    data_root.mkdir(mode=0o700)
    missing_socket_directory = data_root / "postgres" / "socket"
    services = RuntimeServices.from_environment(
        environ={"RSI_ATLAS_DATA_ROOT": str(data_root)},
        database_conninfo=(f"host='{missing_socket_directory}' user='atlas' dbname='atlas'"),
        resource_sampler=SafeResourceSampler(),
        clock=lambda: CHECKED_AT,
    )

    status = services.status()

    offline = next(item for item in status.components if item.component_id == "offline_policy")
    assert offline.state is HealthState.UNSAFE
    assert offline.summary == "The strict offline boundary could not be verified."
    assert offline.remediation == (
        "Restore the exact local socket and loopback policy, then refresh."
    )
    assert str(missing_socket_directory) not in status.model_dump_json()


@pytest.mark.parametrize(
    "captured_at",
    [CHECKED_AT - timedelta(seconds=6), CHECKED_AT + timedelta(microseconds=1)],
    ids=["stale", "future"],
)
def test_resource_policy_blocks_stale_and_future_samples(
    tmp_path: Path,
    captured_at: datetime,
) -> None:
    data_root = tmp_path / "runtime"
    data_root.mkdir(mode=0o700)
    services = RuntimeServices.from_environment(
        environ={"RSI_ATLAS_DATA_ROOT": str(data_root)},
        resource_sampler=FixedResourceSampler(captured_at),
        clock=lambda: CHECKED_AT,
    )

    status = services.status()

    resource = next(item for item in status.components if item.component_id == "resource_policy")
    assert resource.state is HealthState.BLOCKED
    assert resource.summary == "Current memory, swap, or thermal state blocks local work."
    assert resource.remediation == (
        "Reduce system pressure and refresh before starting bounded work."
    )


@pytest.mark.parametrize(
    "snapshot",
    [
        ResourceSnapshot(
            free_bytes=4 * 1024**3 - 1,
            swap_bytes=0,
            thermal=ThermalState.NOMINAL,
            captured_at=CHECKED_AT,
        ),
        ResourceSnapshot(
            free_bytes=8 * 1024**3,
            swap_bytes=16 * 1024**3 + 1,
            thermal=ThermalState.NOMINAL,
            captured_at=CHECKED_AT,
        ),
        ResourceSnapshot(
            free_bytes=8 * 1024**3,
            swap_bytes=0,
            thermal=ThermalState.SERIOUS,
            captured_at=CHECKED_AT,
        ),
    ],
    ids=["low-memory", "high-swap", "unsafe-thermal"],
)
def test_resource_policy_blocks_unsafe_samples(
    tmp_path: Path,
    snapshot: ResourceSnapshot,
) -> None:
    class SnapshotSampler:
        def sample(self) -> ResourceSnapshot:
            return snapshot

    data_root = tmp_path / "runtime"
    data_root.mkdir(mode=0o700)
    services = RuntimeServices.from_environment(
        environ={"RSI_ATLAS_DATA_ROOT": str(data_root)},
        resource_sampler=SnapshotSampler(),
        clock=lambda: CHECKED_AT,
    )

    resource = next(
        item for item in services.status().components if item.component_id == "resource_policy"
    )

    assert resource.state is HealthState.BLOCKED
    assert resource.remediation is not None


@pytest.mark.parametrize(
    ("check_name", "component_id", "expected_state"),
    [
        ("_check_database", "database", HealthState.BLOCKED),
        ("_check_artifact_store", "artifact_store", HealthState.REPAIRABLE),
        ("_check_offline_policy", "offline_policy", HealthState.UNSAFE),
        ("_check_trace_store", "trace_store", HealthState.REPAIRABLE),
        ("_check_resource_policy", "resource_policy", HealthState.BLOCKED),
        ("_check_model_registry", "model_registry", HealthState.BLOCKED),
    ],
)
def test_every_fallible_default_probe_maps_failure_to_typed_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    check_name: str,
    component_id: str,
    expected_state: HealthState,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> ProbeObservation:
        raise RuntimeError("secret=/private/injected")

    monkeypatch.setattr(runtime_module, check_name, fail)
    data_root = tmp_path / "runtime"
    data_root.mkdir(mode=0o700)
    services = RuntimeServices.from_environment(
        environ={"RSI_ATLAS_DATA_ROOT": str(data_root)},
        resource_sampler=SafeResourceSampler(),
        clock=lambda: CHECKED_AT,
    )

    status = services.status()
    component = next(item for item in status.components if item.component_id == component_id)

    assert component.state is expected_state
    assert component.remediation is not None
    assert "secret" not in status.model_dump_json()
    assert "/private" not in status.model_dump_json()


def test_real_runtime_probes_and_disposable_integrity_recovery(tmp_path: Path) -> None:
    conninfo = os.environ.get("RSI_ATLAS_TEST_DATABASE_URL")
    if conninfo is None:
        pytest.skip("real PostgreSQL integration URL is required")
    data_root = tmp_path / "runtime"
    data_root.mkdir(mode=0o700)
    paths = RuntimePaths.from_data_root(data_root)
    services = RuntimeServices.from_environment(
        environ={"RSI_ATLAS_DATA_ROOT": str(data_root)},
        database_conninfo=conninfo,
        resource_sampler=SafeResourceSampler(),
        clock=lambda: CHECKED_AT,
    )

    healthy = services.status()

    assert tuple(component.component_id for component in healthy.components) == COMPONENT_IDS
    assert healthy.state is HealthState.DEGRADED
    assert (
        next(item.state for item in healthy.components if item.component_id == "model_registry")
        is HealthState.DEGRADED
    )
    assert all(
        item.state is HealthState.HEALTHY
        for item in healthy.components
        if item.component_id != "model_registry"
    )

    store = ContentAddressedArtifactStore(paths.artifact_root)
    sentinel_path = store.payload_path(RUNTIME_SENTINEL_ID)
    sentinel_path.write_bytes(b"corrupted-runtime-sentinel")
    sentinel_path.chmod(0o600)

    corrupted = services.status()
    artifact = next(item for item in corrupted.components if item.component_id == "artifact_store")
    assert artifact.state is HealthState.REPAIRABLE
    assert artifact.remediation is not None

    sentinel_path.write_bytes(RUNTIME_SENTINEL_BYTES)
    sentinel_path.chmod(0o600)
    recovered = services.status()
    assert (
        next(item.state for item in recovered.components if item.component_id == "artifact_store")
        is HealthState.HEALTHY
    )

    paths.trace_path.write_bytes(b"partial")
    paths.trace_path.chmod(0o600)
    trace_corrupted = services.status()
    assert (
        next(
            item.state for item in trace_corrupted.components if item.component_id == "trace_store"
        )
        is HealthState.REPAIRABLE
    )

    paths.trace_path.write_bytes(b"")
    paths.trace_path.chmod(0o600)
    trace_recovered = services.status()
    assert (
        next(
            item.state for item in trace_recovered.components if item.component_id == "trace_store"
        )
        is HealthState.HEALTHY
    )


def test_database_probe_bounds_migration_lock_contention(tmp_path: Path) -> None:
    conninfo = os.environ.get("RSI_ATLAS_TEST_DATABASE_URL")
    if conninfo is None:
        pytest.skip("real PostgreSQL integration URL is required")
    data_root = tmp_path / "runtime"
    data_root.mkdir(mode=0o700)
    services = RuntimeServices.from_environment(
        environ={"RSI_ATLAS_DATA_ROOT": str(data_root)},
        database_conninfo=conninfo,
        resource_sampler=SafeResourceSampler(),
        clock=lambda: CHECKED_AT,
    )
    blocker = PostgresDatabase(DatabaseSettings.from_conninfo(conninfo))

    with blocker.connect() as connection:
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (0x52534941544C4153,))
        started_at = monotonic()
        status = services.status()
        elapsed = monotonic() - started_at

    database = next(item for item in status.components if item.component_id == "database")
    assert elapsed < 5
    assert database.state is HealthState.BLOCKED
    assert database.remediation == ("Start the project-owned PostgreSQL runtime, then refresh.")


def test_database_probe_retries_and_recovers_in_same_runtime_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conninfo = os.environ.get("RSI_ATLAS_TEST_DATABASE_URL")
    if conninfo is None:
        pytest.skip("real PostgreSQL integration URL is required")
    data_root = tmp_path / "runtime"
    data_root.mkdir(mode=0o700)
    original_apply_all = MigrationRunner.apply_all
    attempts = 0

    def fail_once(
        runner: MigrationRunner,
        *,
        connection: object | None = None,
    ) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("injected migration interruption")
        original_apply_all(runner, connection=connection)

    monkeypatch.setattr(MigrationRunner, "apply_all", fail_once)
    services = RuntimeServices.from_environment(
        environ={"RSI_ATLAS_DATA_ROOT": str(data_root)},
        database_conninfo=conninfo,
        resource_sampler=SafeResourceSampler(),
        clock=lambda: CHECKED_AT,
    )

    first = services.status()
    recovered = services.status()

    assert next(item for item in first.components if item.component_id == "database").state is (
        HealthState.BLOCKED
    )
    assert (
        next(item for item in recovered.components if item.component_id == "database").state
        is HealthState.HEALTHY
    )
