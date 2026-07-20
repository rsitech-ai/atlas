from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import os
import stat
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar, Protocol
from uuid import UUID

from rsi_atlas_contracts import (
    ArtifactCommandContext,
    ArtifactID,
    ComponentGroup,
    ComponentStatus,
    HealthState,
    ProviderHealthState,
    ResourceClass,
    RuntimeProfile,
    SystemStatus,
    ThermalState,
)
from rsi_atlas_models import (
    ModelRegistry,
    ResourceArbiter,
    ResourcePolicy,
    ResourceSnapshot,
    UnavailableModelProvider,
)
from rsi_atlas_observability import TraceRuntime
from rsi_atlas_security import NetworkPolicy, ProcessRole
from rsi_atlas_storage import (
    ContentAddressedArtifactStore,
    DatabaseSettings,
    MigrationRunner,
    PostgresDatabase,
)

from rsi_atlas_engine.diagnostics import build_system_status
from rsi_atlas_engine.safe_mode import apply_or_verify_migrations, runtime_safe_mode

COMPONENT_IDS = (
    "engine_runtime",
    "database",
    "artifact_store",
    "offline_policy",
    "trace_store",
    "resource_policy",
    "model_registry",
    "contract_api",
)
RUNTIME_SENTINEL_BYTES = b"rsi-atlas-runtime-integrity-probe-v1\n"
RUNTIME_SENTINEL_ID = ArtifactID(f"sha256:{hashlib.sha256(RUNTIME_SENTINEL_BYTES).hexdigest()}")
_RUNTIME_CONTEXT = ArtifactCommandContext(
    tenant_id=UUID("11111111-1111-4111-8111-111111111111"),
    workspace_id=UUID("22222222-2222-4222-8222-222222222222"),
    actor_id=UUID("33333333-3333-4333-8333-333333333333"),
    trace_id=UUID("44444444-4444-4444-8444-444444444444"),
)
_EXPECTED_VECTOR_VERSION = "0.8.5"
_LOOPBACK_ORIGIN = "http://127.0.0.1:8765"
_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_DATABASE_CONNECT_TIMEOUT_SECONDS = 1
_DATABASE_TRANSACTION_TIMEOUT_MS = 3_000


@dataclass(frozen=True, slots=True)
class ProbeObservation:
    state: HealthState
    summary: str
    remediation: str | None = None


@dataclass(frozen=True, slots=True)
class RuntimeProbe:
    component_id: str
    title: str
    group: ComponentGroup
    check: Callable[[], ProbeObservation]
    failure_state: HealthState
    failure_summary: str
    failure_remediation: str | None

    def run(self) -> ComponentStatus:
        try:
            observation = self.check()
            if type(observation) is not ProbeObservation:
                raise TypeError("runtime probe returned an invalid observation")
            return ComponentStatus(
                component_id=self.component_id,
                title=self.title,
                group=self.group,
                state=observation.state,
                summary=observation.summary,
                remediation=observation.remediation,
            )
        except Exception:
            return ComponentStatus(
                component_id=self.component_id,
                title=self.title,
                group=self.group,
                state=self.failure_state,
                summary=self.failure_summary,
                remediation=self.failure_remediation,
            )


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    repository_root: Path
    data_root: Path
    artifact_root: Path
    trace_path: Path
    migration_root: Path

    @classmethod
    def from_environment(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        repository_root: Path | None = None,
    ) -> RuntimePaths:
        values = os.environ if environ is None else environ
        root = repository_root or Path(__file__).resolve().parents[4]
        raw_data_root = values.get("RSI_ATLAS_DATA_ROOT")
        data_root = Path(raw_data_root) if raw_data_root is not None else root / ".local"
        return cls.from_data_root(data_root, repository_root=root)

    @classmethod
    def from_data_root(
        cls,
        data_root: Path,
        *,
        repository_root: Path | None = None,
    ) -> RuntimePaths:
        if not isinstance(data_root, Path) or not data_root.is_absolute():
            raise ValueError("runtime data root must be absolute")
        if data_root != Path(os.path.normpath(data_root)):
            raise ValueError("runtime data root must be canonical")
        rendered = str(data_root)
        if "'" in rendered or any(ord(character) < 32 for character in rendered):
            raise ValueError("runtime data root contains unsupported characters")
        cls._ensure_owner_private_directory(data_root)
        root = repository_root or Path(__file__).resolve().parents[4]
        if not root.is_absolute() or not (root / "migrations").is_dir():
            raise ValueError("runtime repository root is invalid")
        return cls(
            repository_root=root,
            data_root=data_root,
            artifact_root=data_root / "artifacts",
            trace_path=data_root / "traces" / "traces.jsonl",
            migration_root=root / "migrations",
        )

    @staticmethod
    def _ensure_owner_private_directory(path: Path) -> None:
        descriptor = -1
        parent_descriptor = -1
        try:
            try:
                descriptor = RuntimePaths._open_absolute_directory(path)
            except FileNotFoundError:
                parent_descriptor = RuntimePaths._open_absolute_directory(path.parent)
                with suppress(FileExistsError):
                    os.mkdir(path.name, mode=0o700, dir_fd=parent_descriptor)
                descriptor = os.open(
                    path.name,
                    _DIRECTORY_OPEN_FLAGS,
                    dir_fd=parent_descriptor,
                )
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISDIR(metadata.st_mode)
                or metadata.st_uid != os.getuid()
                or stat.S_IMODE(metadata.st_mode) != 0o700
            ):
                raise ValueError("runtime data root must be owner-private")
        except OSError as error:
            raise ValueError("runtime data root must not contain symlinks") from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if parent_descriptor >= 0:
                os.close(parent_descriptor)

    @staticmethod
    def _open_absolute_directory(path: Path) -> int:
        descriptor = os.open(os.sep, _DIRECTORY_OPEN_FLAGS)
        try:
            for component in path.parts[1:]:
                next_descriptor = os.open(
                    component,
                    _DIRECTORY_OPEN_FLAGS,
                    dir_fd=descriptor,
                )
                os.close(descriptor)
                descriptor = next_descriptor
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise


class _SwapUsage(ctypes.Structure):
    _fields_: ClassVar[list[tuple[str, type]]] = [
        ("total", ctypes.c_uint64),
        ("available", ctypes.c_uint64),
        ("used", ctypes.c_uint64),
        ("page_size", ctypes.c_uint32),
        ("encrypted", ctypes.c_bool),
    ]


class MacResourceSampler:
    _THERMAL_NOTIFICATION = b"com.apple.system.thermalpressurelevel"

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("macOS resource sampling is unavailable")
        library_path = ctypes.util.find_library("System")
        if library_path is None:
            raise RuntimeError("macOS system library is unavailable")
        self._system = ctypes.CDLL(library_path, use_errno=True)

    def sample(self) -> ResourceSnapshot:
        physical_bytes = self._sysctl_scalar(b"hw.memsize", ctypes.c_uint64)
        memory_level = self._sysctl_scalar(b"kern.memorystatus_level", ctypes.c_int32)
        if physical_bytes <= 0 or not 0 <= memory_level <= 100:
            raise RuntimeError("macOS memory status is invalid")
        swap = self._sysctl_structure(b"vm.swapusage", _SwapUsage)
        if swap.used > swap.total:
            raise RuntimeError("macOS swap status is invalid")
        thermal = self._thermal_state()
        return ResourceSnapshot(
            free_bytes=physical_bytes * memory_level // 100,
            swap_bytes=swap.used,
            thermal=thermal,
            captured_at=datetime.now(UTC),
        )

    def _sysctl_scalar(
        self,
        name: bytes,
        value_type: type[ctypes.c_uint64] | type[ctypes.c_int32],
    ) -> int:
        value = value_type()
        size = ctypes.c_size_t(ctypes.sizeof(value))
        function = self._system.sysctlbyname
        function.argtypes = [
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        function.restype = ctypes.c_int
        if function(name, ctypes.byref(value), ctypes.byref(size), None, 0) != 0:
            raise RuntimeError("macOS sysctl query failed")
        if size.value != ctypes.sizeof(value):
            raise RuntimeError("macOS sysctl value size is invalid")
        return int(value.value)

    def _sysctl_structure(self, name: bytes, value_type: type[_SwapUsage]) -> _SwapUsage:
        value = value_type()
        size = ctypes.c_size_t(ctypes.sizeof(value))
        function = self._system.sysctlbyname
        function.argtypes = [
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_size_t),
            ctypes.c_void_p,
            ctypes.c_size_t,
        ]
        function.restype = ctypes.c_int
        if function(name, ctypes.byref(value), ctypes.byref(size), None, 0) != 0:
            raise RuntimeError("macOS sysctl query failed")
        if size.value != ctypes.sizeof(value):
            raise RuntimeError("macOS sysctl value size is invalid")
        return value

    def _thermal_state(self) -> ThermalState:
        token = ctypes.c_int()
        state = ctypes.c_uint64()
        register = self._system.notify_register_check
        register.argtypes = [ctypes.c_char_p, ctypes.POINTER(ctypes.c_int)]
        register.restype = ctypes.c_uint32
        get_state = self._system.notify_get_state
        get_state.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint64)]
        get_state.restype = ctypes.c_uint32
        cancel = self._system.notify_cancel
        cancel.argtypes = [ctypes.c_int]
        cancel.restype = ctypes.c_uint32
        if register(self._THERMAL_NOTIFICATION, ctypes.byref(token)) != 0:
            raise RuntimeError("macOS thermal status is unavailable")
        try:
            if get_state(token, ctypes.byref(state)) != 0:
                raise RuntimeError("macOS thermal status is unavailable")
        finally:
            cancel(token)
        states = {
            0: ThermalState.NOMINAL,
            1: ThermalState.FAIR,
            2: ThermalState.SERIOUS,
            3: ThermalState.CRITICAL,
        }
        try:
            return states[state.value]
        except KeyError as error:
            raise RuntimeError("macOS thermal status is invalid") from error


class ResourceSampling(Protocol):
    def sample(self) -> ResourceSnapshot: ...


class RuntimeServices:
    def __init__(
        self,
        *,
        probes: Sequence[RuntimeProbe],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        configured = tuple(probes)
        if tuple(probe.component_id for probe in configured) != COMPONENT_IDS:
            raise ValueError("runtime services require the exact runtime probes")
        self._probes = configured
        self._clock = clock

    @classmethod
    def from_environment(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        database_conninfo: str | None = None,
        resource_sampler: ResourceSampling | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> RuntimeServices:
        values = os.environ if environ is None else environ
        try:
            paths = RuntimePaths.from_environment(environ=values)
        except (OSError, ValueError):
            return cls(probes=_configuration_failure_probes(), clock=clock)
        socket_directory = paths.data_root / "postgres" / "socket"
        conninfo = database_conninfo or (
            f"host='{socket_directory}' port=5432 user='atlas' dbname='atlas'"
        )
        return cls(
            probes=_default_probes(
                paths=paths,
                conninfo=conninfo,
                sampler=resource_sampler,
                clock=clock,
            ),
            clock=clock,
        )

    def status(self) -> SystemStatus:
        components = tuple(probe.run() for probe in self._probes)
        return build_system_status(
            clock=self._clock,
            profile=RuntimeProfile.OFFLINE,
            components=components,
        )


def _observation(
    state: HealthState,
    summary: str,
    remediation: str | None = None,
) -> ProbeObservation:
    return ProbeObservation(state=state, summary=summary, remediation=remediation)


def _static_probe(
    component_id: str,
    title: str,
    group: ComponentGroup,
    observation: ProbeObservation,
) -> RuntimeProbe:
    return RuntimeProbe(
        component_id=component_id,
        title=title,
        group=group,
        check=lambda: observation,
        failure_state=HealthState.BLOCKED,
        failure_summary="The runtime check failed.",
        failure_remediation="Review the local runtime configuration.",
    )


def _default_probes(
    *,
    paths: RuntimePaths,
    conninfo: str,
    sampler: ResourceSampling | None,
    clock: Callable[[], datetime],
) -> tuple[RuntimeProbe, ...]:
    return (
        _static_probe(
            "engine_runtime",
            "Engine Runtime",
            ComponentGroup.ENGINE,
            _observation(
                HealthState.HEALTHY,
                "The local engine can evaluate runtime diagnostics.",
            ),
        ),
        RuntimeProbe(
            component_id="database",
            title="Database",
            group=ComponentGroup.STORAGE,
            check=lambda: _check_database(paths, conninfo),
            failure_state=HealthState.BLOCKED,
            failure_summary="PostgreSQL or pgvector is unavailable.",
            failure_remediation="Start the project-owned PostgreSQL runtime, then refresh.",
        ),
        RuntimeProbe(
            component_id="artifact_store",
            title="Artifact Store",
            group=ComponentGroup.STORAGE,
            check=lambda: _check_artifact_store(paths),
            failure_state=HealthState.REPAIRABLE,
            failure_summary="The runtime integrity sentinel failed verification.",
            failure_remediation="Restore the disposable runtime sentinel from known bytes.",
        ),
        RuntimeProbe(
            component_id="offline_policy",
            title="Offline Policy",
            group=ComponentGroup.PRIVACY,
            check=lambda: _check_offline_policy(conninfo),
            failure_state=HealthState.UNSAFE,
            failure_summary="The strict offline boundary could not be verified.",
            failure_remediation="Restore the exact local socket and loopback policy, then refresh.",
        ),
        RuntimeProbe(
            component_id="trace_store",
            title="Trace Store",
            group=ComponentGroup.OBSERVABILITY,
            check=lambda: _check_trace_store(paths),
            failure_state=HealthState.REPAIRABLE,
            failure_summary="The private metadata trace store failed validation.",
            failure_remediation="Repair the owner-private trace file before collecting new spans.",
        ),
        RuntimeProbe(
            component_id="resource_policy",
            title="Resource Policy",
            group=ComponentGroup.RESOURCES,
            check=lambda: _check_resource_policy(sampler or MacResourceSampler(), clock),
            failure_state=HealthState.BLOCKED,
            failure_summary="Current memory, swap, or thermal state blocks local work.",
            failure_remediation="Reduce system pressure and refresh before starting bounded work.",
        ),
        RuntimeProbe(
            component_id="model_registry",
            title="Model Registry",
            group=ComponentGroup.RESOURCES,
            check=_check_model_registry,
            failure_state=HealthState.BLOCKED,
            failure_summary="The model boundary could not be verified.",
            failure_remediation="Repair the local model metadata boundary before use.",
        ),
        _static_probe(
            "contract_api",
            "Contract API",
            ComponentGroup.ENGINE,
            _observation(
                HealthState.HEALTHY,
                "The versioned local status contract is available.",
            ),
        ),
    )


def _configuration_failure_probes() -> tuple[RuntimeProbe, ...]:
    configured = {
        "engine_runtime": _observation(
            HealthState.HEALTHY,
            "The local engine can evaluate runtime diagnostics.",
        ),
        "database": _observation(
            HealthState.BLOCKED,
            "Database configuration is unavailable.",
            "Restore the owner-private local data root, then refresh.",
        ),
        "artifact_store": _observation(
            HealthState.BLOCKED,
            "Artifact storage configuration is unavailable.",
            "Restore the owner-private local data root, then refresh.",
        ),
        "offline_policy": _observation(
            HealthState.UNSAFE,
            "The strict offline boundary could not be configured.",
            "Restore the owner-private local data root before continuing.",
        ),
        "trace_store": _observation(
            HealthState.BLOCKED,
            "Trace storage configuration is unavailable.",
            "Restore the owner-private local data root, then refresh.",
        ),
        "resource_policy": _observation(
            HealthState.BLOCKED,
            "Resource policy initialization is blocked.",
            "Restore the local runtime configuration, then refresh.",
        ),
        "model_registry": _observation(
            HealthState.DEGRADED,
            "No production-qualified local model or provider is active.",
            "Select and admit a provider only after governed evaluation and owner approval.",
        ),
        "contract_api": _observation(
            HealthState.HEALTHY,
            "The versioned local status contract is available.",
        ),
    }
    titles = {
        "engine_runtime": "Engine Runtime",
        "database": "Database",
        "artifact_store": "Artifact Store",
        "offline_policy": "Offline Policy",
        "trace_store": "Trace Store",
        "resource_policy": "Resource Policy",
        "model_registry": "Model Registry",
        "contract_api": "Contract API",
    }
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
        _static_probe(
            component_id, titles[component_id], groups[component_id], configured[component_id]
        )
        for component_id in COMPONENT_IDS
    )


def _check_database(paths: RuntimePaths, conninfo: str) -> ProbeObservation:
    database = PostgresDatabase(
        DatabaseSettings.from_conninfo(
            conninfo,
            connect_timeout_seconds=_DATABASE_CONNECT_TIMEOUT_SECONDS,
            statement_timeout_ms=1_500,
            lock_timeout_ms=750,
            transaction_timeout_ms=_DATABASE_TRANSACTION_TIMEOUT_MS,
        )
    )
    migration_runner = MigrationRunner(database, paths.migration_root)
    expected_migrations = list(migration_runner.expected_versions())
    with database.connect() as connection:
        apply_or_verify_migrations(
            migration_runner,
            runtime_safe_mode(environ={"RSI_ATLAS_DATA_ROOT": str(paths.data_root)}),
            connection=connection,
        )
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    current_setting('listen_addresses'),
                    (SELECT extversion FROM pg_extension WHERE extname = 'vector'),
                    (SELECT array_agg(version ORDER BY version) FROM atlas_meta.schema_migrations)
                """
            )
            row = cursor.fetchone()
    if row != ("", _EXPECTED_VECTOR_VERSION, expected_migrations):
        raise RuntimeError("database readiness does not match checked-in migrations")
    return _observation(
        HealthState.HEALTHY,
        "PostgreSQL and pgvector are ready on the project-owned Unix socket.",
    )


def _check_artifact_store(paths: RuntimePaths) -> ProbeObservation:
    store = ContentAddressedArtifactStore(paths.artifact_root)
    descriptor = store.put_bytes(
        RUNTIME_SENTINEL_BYTES,
        media_type="application/vnd.rsi-atlas.runtime-sentinel",
        context=_RUNTIME_CONTEXT,
    )
    if descriptor.artifact_id != RUNTIME_SENTINEL_ID:
        raise RuntimeError("runtime sentinel identity changed")
    store.verify(RUNTIME_SENTINEL_ID, context=_RUNTIME_CONTEXT)
    return _observation(
        HealthState.HEALTHY,
        "The immutable runtime integrity sentinel verifies successfully.",
    )


def _check_offline_policy(conninfo: str) -> ProbeObservation:
    settings = DatabaseSettings.from_conninfo(conninfo)
    socket_path = settings.socket_directory / f".s.PGSQL.{settings.port}"
    if not socket_path.exists():
        raise RuntimeError("project PostgreSQL socket is unavailable")
    policy = NetworkPolicy.offline(
        loopback_origins=[_LOOPBACK_ORIGIN],
        unix_socket_paths=[socket_path],
    )
    remote = policy.authorize(
        role=ProcessRole.ENGINE,
        scheme="https",
        host="example.com",
        port=443,
    )
    loopback = policy.authorize(
        role=ProcessRole.API,
        scheme="http",
        host="127.0.0.1",
        port=8765,
    )
    if remote.allowed or not loopback.allowed:
        raise RuntimeError("offline network decision is invalid")
    local_socket = policy.authorize(
        role=ProcessRole.ENGINE,
        unix_socket_path=socket_path,
    )
    if not local_socket.allowed:
        raise RuntimeError("offline local socket decision is invalid")
    return _observation(
        HealthState.HEALTHY,
        "Remote network access is denied and local boundaries are exact.",
    )


def _check_trace_store(paths: RuntimePaths) -> ProbeObservation:
    paths.trace_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    runtime = TraceRuntime.local(paths.trace_path)
    try:
        if not runtime.force_flush():
            raise RuntimeError("trace flush failed")
    finally:
        runtime.shutdown()
    return _observation(
        HealthState.HEALTHY,
        "Metadata-only traces use owner-private local storage.",
    )


def _check_resource_policy(
    sampler: ResourceSampling,
    clock: Callable[[], datetime],
) -> ProbeObservation:
    snapshot = sampler.sample()
    policy = ResourcePolicy(
        min_free_bytes=4 * 1024**3,
        max_swap_bytes=16 * 1024**3,
        allowed_thermal=frozenset({ThermalState.NOMINAL, ThermalState.FAIR}),
        max_snapshot_age=timedelta(seconds=5),
        max_light_leases=1,
    )
    arbiter = ResourceArbiter(policy, clock=clock)
    with arbiter.acquire(
        UUID("55555555-5555-4555-8555-555555555555"),
        ResourceClass.LIGHT,
        snapshot,
    ):
        pass
    return _observation(
        HealthState.HEALTHY,
        "Current memory, swap, and thermal state admit bounded local work.",
    )


def _check_model_registry() -> ProbeObservation:
    registry = ModelRegistry()
    provider = UnavailableModelProvider()
    if (
        registry.snapshot()
        or provider.capabilities
        or provider.health.state is not ProviderHealthState.UNAVAILABLE
    ):
        raise RuntimeError("runtime model boundary is invalid")
    provider.unload()
    return _observation(
        HealthState.DEGRADED,
        "No production-qualified local model or provider is active.",
        "Select and admit a provider only after governed evaluation and owner approval.",
    )


__all__ = [
    "COMPONENT_IDS",
    "RUNTIME_SENTINEL_BYTES",
    "RUNTIME_SENTINEL_ID",
    "MacResourceSampler",
    "ProbeObservation",
    "RuntimePaths",
    "RuntimeProbe",
    "RuntimeServices",
]
