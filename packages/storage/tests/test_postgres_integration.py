import importlib.util
import os
import select
import shutil
import stat
import struct
import subprocess
import tempfile
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from rsi_atlas_contracts import ArtifactCommandContext, ArtifactIntegrityError
from rsi_atlas_storage import (
    ArtifactRepository,
    ContentAddressedArtifactStore,
    DatabaseSettings,
    MigrationIntegrityError,
    MigrationRunner,
    PostgresDatabase,
)

SECURE_PATH_SPEC = importlib.util.spec_from_file_location(
    "rsi_atlas_secure_path", "infra/local/secure_path.py"
)
assert SECURE_PATH_SPEC is not None and SECURE_PATH_SPEC.loader is not None
secure_path = importlib.util.module_from_spec(SECURE_PATH_SPEC)
SECURE_PATH_SPEC.loader.exec_module(secure_path)


class FakeBootstrapSocket:
    def __init__(self, payload: bytes = b"", *, timeout_on_recv: bool = False) -> None:
        self.payload = bytearray(payload)
        self.timeout_on_recv = timeout_on_recv
        self.recv_sizes: list[int] = []
        self.sent: list[bytes] = []

    def recv(self, size: int) -> bytes:
        self.recv_sizes.append(size)
        if self.timeout_on_recv:
            raise TimeoutError("injected timeout")
        result = bytes(self.payload[:size])
        del self.payload[:size]
        return result

    def sendall(self, payload: bytes) -> None:
        self.sent.append(payload)

    def settimeout(self, timeout: float) -> None:
        assert timeout > 0


def _backend_message(message_type: bytes, payload: bytes) -> bytes:
    return message_type + struct.pack("!I", len(payload) + 4) + payload


def _row_description(field_count: int) -> bytes:
    fields = b"".join(
        f"column_{index}".encode() + b"\0" + (b"\0" * 18) for index in range(field_count)
    )
    return struct.pack("!H", field_count) + fields


def _data_row(values: list[bytes]) -> bytes:
    return struct.pack("!H", len(values)) + b"".join(
        struct.pack("!i", len(value)) + value for value in values
    )


@pytest.fixture(scope="session")
def postgres_database() -> Iterator[PostgresDatabase]:
    conninfo = os.environ["RSI_ATLAS_TEST_DATABASE_URL"]
    database = PostgresDatabase(DatabaseSettings.from_conninfo(conninfo))
    MigrationRunner(database, Path("migrations")).apply_all()
    yield database


def _context(
    *, tenant_id: UUID | None = None, workspace_id: UUID | None = None
) -> ArtifactCommandContext:
    return ArtifactCommandContext(
        tenant_id=tenant_id or uuid4(),
        workspace_id=workspace_id or uuid4(),
        actor_id=uuid4(),
        trace_id=uuid4(),
    )


def test_migrations_enable_vector_and_are_idempotent(
    postgres_database: PostgresDatabase,
) -> None:
    runner = MigrationRunner(postgres_database, Path("migrations"))

    runner.apply_all()
    runner.apply_all()

    assert postgres_database.fetch_value(
        "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
    )
    assert postgres_database.fetch_value("SELECT count(*) FROM atlas_meta.schema_migrations") == 2


def test_fresh_database_migrations_serialize_concurrent_runners(
    postgres_database: PostgresDatabase,
) -> None:
    database_name = f"atlas_concurrency_{uuid4().hex}"
    with postgres_database.connect(autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    settings = DatabaseSettings.from_conninfo(
        f"host={postgres_database.settings.socket_directory} "
        f"user={postgres_database.settings.user} dbname={database_name}"
    )
    fresh_database = PostgresDatabase(settings)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(MigrationRunner(fresh_database, Path("migrations")).apply_all)
                for _ in range(2)
            ]
            for future in futures:
                future.result()
        assert fresh_database.fetch_value("SELECT count(*) FROM atlas_meta.schema_migrations") == 2
    finally:
        with postgres_database.connect(autocommit=True) as connection:
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(database_name))
            )


def test_migration_bytes_are_hash_locked(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    migration_directory = tmp_path / "migrations"
    shutil.copytree("migrations", migration_directory)
    migration_path = migration_directory / "0001_foundation.sql"
    migration_path.write_text(migration_path.read_text() + "\n-- modified\n")

    with pytest.raises(MigrationIntegrityError, match="checksum"):
        MigrationRunner(postgres_database, migration_directory).apply_all()


def test_artifact_metadata_requires_verified_bytes(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    context = _context()
    artifact_store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    descriptor = artifact_store.put_bytes(
        b"evidence", media_type="application/pdf", context=context
    )
    artifact_store.payload_path(descriptor.artifact_id).unlink()
    repository = ArtifactRepository(postgres_database, artifact_store)

    with pytest.raises(ArtifactIntegrityError):
        repository.register(context=context, descriptor=descriptor)

    assert repository.find(context=context, artifact_id=descriptor.artifact_id) is None


def test_find_fails_closed_when_registered_bytes_disappear(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    context = _context()
    artifact_store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    descriptor = artifact_store.put_bytes(
        b"registered evidence", media_type="application/pdf", context=context
    )
    repository = ArtifactRepository(postgres_database, artifact_store)
    repository.register(context=context, descriptor=descriptor)
    artifact_store.payload_path(descriptor.artifact_id).unlink()

    with pytest.raises(ArtifactIntegrityError):
        repository.find(context=context, artifact_id=descriptor.artifact_id)


def test_registration_is_scoped_and_records_actor_and_trace(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    tenant_id = uuid4()
    workspace_id = uuid4()
    context = _context(tenant_id=tenant_id, workspace_id=workspace_id)
    other_workspace = _context(tenant_id=tenant_id)
    artifact_store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    descriptor = artifact_store.put_bytes(
        b"scoped evidence", media_type="application/pdf", context=context
    )
    repository = ArtifactRepository(postgres_database, artifact_store)

    assert repository.register(context=context, descriptor=descriptor) == descriptor
    assert repository.find(context=context, artifact_id=descriptor.artifact_id) == descriptor
    assert repository.find(context=other_workspace, artifact_id=descriptor.artifact_id) is None
    assert postgres_database.fetch_one(
        """
        SELECT registered_by_actor_id, registration_trace_id
        FROM atlas_core.artifact_references
        WHERE tenant_id = %s AND workspace_id = %s AND artifact_id = %s
        """,
        (tenant_id, workspace_id, str(descriptor.artifact_id)),
    ) == (context.actor_id, context.trace_id)


def test_workspace_cannot_be_rebound_to_another_tenant(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    workspace_id = uuid4()
    first = _context(workspace_id=workspace_id)
    second = _context(workspace_id=workspace_id)
    artifact_store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    descriptor = artifact_store.put_bytes(
        b"tenant boundary", media_type="application/pdf", context=first
    )
    repository = ArtifactRepository(postgres_database, artifact_store)
    repository.register(context=first, descriptor=descriptor)

    with pytest.raises(PermissionError, match="workspace"):
        repository.register(context=second, descriptor=descriptor)

    assert repository.find(context=second, artifact_id=descriptor.artifact_id) is None


def test_conflicting_content_metadata_rolls_back_reference(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    first_context = _context()
    second_context = _context()
    first_store = ContentAddressedArtifactStore(tmp_path / "first-artifacts")
    second_store = ContentAddressedArtifactStore(tmp_path / "second-artifacts")
    first_descriptor = first_store.put_bytes(
        b"same bytes", media_type="application/pdf", context=first_context
    )
    second_descriptor = second_store.put_bytes(
        b"same bytes", media_type="text/plain", context=second_context
    )
    ArtifactRepository(postgres_database, first_store).register(
        context=first_context, descriptor=first_descriptor
    )
    second_repository = ArtifactRepository(postgres_database, second_store)

    with pytest.raises(ArtifactIntegrityError, match="metadata"):
        second_repository.register(context=second_context, descriptor=second_descriptor)

    assert (
        second_repository.find(context=second_context, artifact_id=second_descriptor.artifact_id)
        is None
    )


def test_artifact_content_rows_are_database_immutable(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    context = _context()
    artifact_store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    descriptor = artifact_store.put_bytes(
        b"immutable database evidence", media_type="application/pdf", context=context
    )
    ArtifactRepository(postgres_database, artifact_store).register(
        context=context, descriptor=descriptor
    )

    with postgres_database.connect() as connection:
        try:
            with pytest.raises(psycopg.Error, match="immutable"):
                connection.execute(
                    "UPDATE atlas_core.artifact_contents SET media_type = %s "
                    "WHERE artifact_id = %s",
                    ("text/plain", str(descriptor.artifact_id)),
                )
        finally:
            connection.rollback()
    with postgres_database.connect() as connection:
        try:
            with pytest.raises(psycopg.Error, match="immutable"):
                connection.execute(
                    "TRUNCATE atlas_core.artifact_references, atlas_core.artifact_contents"
                )
        finally:
            connection.rollback()
    with postgres_database.connect() as connection:
        try:
            with pytest.raises(psycopg.Error, match="immutable"):
                connection.execute(
                    "DELETE FROM atlas_core.artifact_contents WHERE artifact_id = %s",
                    (str(descriptor.artifact_id),),
                )
        finally:
            connection.rollback()

    assert (
        ArtifactRepository(postgres_database, artifact_store).find(
            context=context, artifact_id=descriptor.artifact_id
        )
        == descriptor
    )


def test_database_is_socket_only_and_owner_private(
    postgres_database: PostgresDatabase,
) -> None:
    socket_directory = postgres_database.settings.socket_directory

    assert postgres_database.fetch_value("SHOW listen_addresses") == ""
    assert postgres_database.fetch_value("SHOW data_checksums") == "on"
    server_socket_setting = Path(postgres_database.fetch_value("SHOW unix_socket_directories"))
    assert stat.S_IMODE(socket_directory.stat().st_mode) == 0o700
    data_directory = socket_directory.parent / "data"
    assert data_directory.is_absolute()
    assert (data_directory / server_socket_setting).resolve() == socket_directory.resolve()
    assert stat.S_IMODE(data_directory.stat().st_mode) == 0o700


def test_connect_rejects_libpq_service_and_hostaddr_environment(
    postgres_database: PostgresDatabase,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_file = tmp_path / "pg_service.conf"
    service_file.write_text("[remote]\nhostaddr=127.0.0.1\nport=1\nuser=remote\ndbname=remote\n")
    monkeypatch.setenv("PGSERVICE", "remote")
    monkeypatch.setenv("PGSERVICEFILE", str(service_file))
    monkeypatch.setenv("PGHOSTADDR", "127.0.0.1")

    with pytest.raises(ValueError, match="unsafe libpq environment"):
        postgres_database.fetch_value("SELECT inet_server_addr()")

    monkeypatch.delenv("PGSERVICE")
    monkeypatch.delenv("PGSERVICEFILE")
    monkeypatch.delenv("PGHOSTADDR")
    assert postgres_database.fetch_value("SELECT inet_server_addr()") is None


def test_local_postgres_start_neutralizes_libpq_network_environment(
    tmp_path: Path,
) -> None:
    service_file = tmp_path / "pg_service.conf"
    service_file.write_text("[remote]\nhostaddr=127.0.0.1\nport=1\nuser=remote\ndbname=remote\n")
    environment = {
        **os.environ,
        "PGSERVICE": "remote",
        "PGSERVICEFILE": str(service_file),
        "PGHOSTADDR": "127.0.0.1",
        "PGPORT": "1",
    }

    result = subprocess.run(
        ["./infra/local/postgres.sh", "start"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0, result.stderr


def test_local_postgres_script_rejects_relative_data_root() -> None:
    environment = {**os.environ, "RSI_ATLAS_DATA_ROOT": "relative/data"}

    result = subprocess.run(
        ["./infra/local/postgres.sh", "test-url"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 2
    assert "absolute path" in result.stderr


@pytest.mark.parametrize("command", ["test-url", "start", "stop", "status", "restart"])
def test_local_postgres_rejects_symlinked_data_root_ancestor(tmp_path: Path, command: str) -> None:
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)
    data_root = linked_parent / "atlas-data"

    result = subprocess.run(
        ["./infra/local/postgres.sh", command],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "RSI_ATLAS_DATA_ROOT": str(data_root)},
    )

    assert result.returncode != 0
    assert "symlink" in result.stderr
    assert not (outside / "atlas-data").exists()


@pytest.mark.parametrize("command", ["stop", "status"])
def test_local_postgres_inspection_does_not_create_missing_root(
    tmp_path: Path, command: str
) -> None:
    data_root = tmp_path / "missing-root"

    result = subprocess.run(
        ["./infra/local/postgres.sh", command],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "RSI_ATLAS_DATA_ROOT": str(data_root)},
    )

    assert result.returncode in {0, 1, 3}
    assert not data_root.exists()


def test_local_postgres_rejects_existing_cluster_without_checksums() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-checksum-", dir="/private/tmp") as root:
        data_root = Path(root) / "root"
        data_directory = data_root / "postgres" / "data"
        subprocess.run(
            [
                "/opt/homebrew/opt/postgresql@17/bin/initdb",
                f"--pgdata={data_directory}",
                "--username=atlas",
                "--auth-local=trust",
                "--auth-host=reject",
                "--encoding=UTF8",
                "--no-locale",
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        result = subprocess.run(
            ["./infra/local/postgres.sh", "start"],
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "RSI_ATLAS_DATA_ROOT": str(data_root)},
        )

        assert result.returncode != 0
        assert "checksums" in result.stderr
        assert not (data_directory / "postmaster.pid").exists()


def test_local_postgres_repairs_existing_data_directory_mode() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-mode-", dir="/private/tmp") as root:
        data_root = Path(root) / "root"
        environment = {**os.environ, "RSI_ATLAS_DATA_ROOT": str(data_root)}
        subprocess.run(
            ["./infra/local/postgres.sh", "start"],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        try:
            subprocess.run(
                ["./infra/local/postgres.sh", "stop"],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )
            data_directory = data_root / "postgres" / "data"
            data_directory.chmod(0o755)

            subprocess.run(
                ["./infra/local/postgres.sh", "start"],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )

            assert stat.S_IMODE(data_directory.stat().st_mode) == 0o700
        finally:
            subprocess.run(
                ["./infra/local/postgres.sh", "stop"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )


def test_local_postgres_supports_absolute_data_root_with_spaces() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas space ", dir="/private/tmp") as root:
        data_root = Path(root) / "data root"
        environment = {**os.environ, "RSI_ATLAS_DATA_ROOT": str(data_root)}
        subprocess.run(
            ["./infra/local/postgres.sh", "start"],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        try:
            conninfo = subprocess.run(
                ["./infra/local/postgres.sh", "test-url"],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            ).stdout.strip()
            database = PostgresDatabase(DatabaseSettings.from_conninfo(conninfo))

            assert database.fetch_value("SELECT inet_server_addr()") is None
        finally:
            subprocess.run(
                ["./infra/local/postgres.sh", "stop"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )


@pytest.mark.parametrize(
    ("command", "bind_mode", "expected_running"),
    [
        ("start", "prepare", True),
        ("stop", "inspect", False),
        ("status", "inspect", True),
        ("restart", "prepare", True),
    ],
)
def test_postgres_lifecycle_stays_bound_after_post_bind_ancestor_swap(
    command: str, bind_mode: str, expected_running: bool
) -> None:
    with tempfile.TemporaryDirectory(prefix=f"atlas-bind-{command}-", dir="/private/tmp") as root:
        data_root = Path(root) / "root"
        environment = {**os.environ, "RSI_ATLAS_DATA_ROOT": str(data_root)}
        subprocess.run(
            ["./infra/local/postgres.sh", "start"],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        if command == "start":
            subprocess.run(
                ["./infra/local/postgres.sh", "stop"],
                check=True,
                capture_output=True,
                text=True,
                env=environment,
            )

        postgres_root = data_root / "postgres"
        bound_root = data_root / f"postgres-bound-{command}"
        outside = Path(root) / "outside"
        outside.mkdir(mode=0o700)
        ready = Path(root) / "ready"
        release = Path(root) / "release"
        wrapper = """
import os
import sys
import time
from pathlib import Path

ready, release, script, command = sys.argv[1:]
Path(ready).touch()
while not Path(release).exists():
    time.sleep(0.01)
os.execve(script, [script, "--bound", command], os.environ)
"""
        process = subprocess.Popen(
            [
                "/usr/bin/python3",
                "infra/local/secure_path.py",
                "exec",
                bind_mode,
                str(data_root),
                "--",
                "/usr/bin/python3",
                "-c",
                wrapper,
                str(ready),
                str(release),
                str(Path("infra/local/postgres.sh").resolve()),
                command,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        try:
            for _ in range(300):
                if ready.exists() or process.poll() is not None:
                    break
                time.sleep(0.01)
            assert ready.exists(), process.communicate(timeout=1)

            postgres_root.rename(bound_root)
            postgres_root.symlink_to(outside, target_is_directory=True)
            release.touch()
            stdout, stderr = process.communicate(timeout=20)

            assert process.returncode == 0, (stdout, stderr)
            assert tuple(outside.iterdir()) == ()
            assert (bound_root / "data" / "PG_VERSION").is_file()
            status = subprocess.run(
                [
                    "/opt/homebrew/opt/postgresql@17/bin/pg_ctl",
                    f"--pgdata={bound_root / 'data'}",
                    "status",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            assert (status.returncode == 0) is expected_running
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            subprocess.run(
                [
                    "/opt/homebrew/opt/postgresql@17/bin/pg_ctl",
                    f"--pgdata={bound_root / 'data'}",
                    "--mode=fast",
                    "--wait",
                    "stop",
                ],
                check=False,
                capture_output=True,
                text=True,
            )


def test_postgres_socket_stays_bound_after_second_ancestor_swap() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-socket-bind-", dir="/private/tmp") as root:
        data_root = Path(root) / "root"
        postgres_root = data_root / "postgres"
        bound_root = data_root / "postgres-bound-second"
        outside = Path(root) / "outside"
        outside.mkdir(mode=0o700)
        outside_socket = outside / "socket"
        outside_socket.mkdir(mode=0o700)
        ready_read, ready_write = os.pipe()
        continue_read, continue_write = os.pipe()
        environment = {
            **os.environ,
            "RSI_ATLAS_DATA_ROOT": str(data_root),
            "RSI_ATLAS_TEST_READY_FD": str(ready_write),
            "RSI_ATLAS_TEST_CONTINUE_FD": str(continue_read),
        }
        process = subprocess.Popen(
            ["./infra/local/postgres.sh", "start"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
            pass_fds=(ready_write, continue_read),
        )
        os.close(ready_write)
        os.close(continue_read)
        try:
            readable, _, _ = select.select([ready_read], [], [], 15)
            assert readable, process.communicate(timeout=1)
            assert os.read(ready_read, 1) == b"1"
            assert (postgres_root / "data" / "PG_VERSION").is_file()

            postgres_root.rename(bound_root)
            postgres_root.symlink_to(outside, target_is_directory=True)
            os.write(continue_write, b"1")
            stdout, stderr = process.communicate(timeout=20)

            assert process.returncode == 0, (stdout, stderr)
            assert tuple(outside_socket.iterdir()) == ()
            socket_entries = {path.name for path in (bound_root / "socket").iterdir()}
            assert ".s.PGSQL.5432" in socket_entries
            assert ".s.PGSQL.5432.lock" in socket_entries
            assert (
                subprocess.run(
                    [
                        "/opt/homebrew/opt/postgresql@17/bin/psql",
                        f"host={bound_root / 'socket'} user=atlas dbname=atlas",
                        "--tuples-only",
                        "--no-align",
                        "--command=SELECT 1",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
                == "1"
            )
        finally:
            os.close(ready_read)
            os.close(continue_write)
            if process.poll() is None:
                process.kill()
                process.wait()
            subprocess.run(
                [
                    "/opt/homebrew/opt/postgresql@17/bin/pg_ctl",
                    f"--pgdata={bound_root / 'data'}",
                    "--mode=fast",
                    "--wait",
                    "stop",
                ],
                check=False,
                capture_output=True,
                text=True,
            )


def test_bootstrap_rejects_oversized_frame_before_payload_read() -> None:
    connection = FakeBootstrapSocket(b"D" + struct.pack("!I", secure_path.MAX_FRAME_BYTES + 1))

    with pytest.raises(secure_path.SecurePathError, match="frame"):
        secure_path._read_message(connection)

    assert max(connection.recv_sizes) <= 4


def test_bootstrap_rejects_truncated_frame_with_domain_error() -> None:
    connection = FakeBootstrapSocket(b"D" + struct.pack("!I", 10) + b"\x00")

    with pytest.raises(secure_path.SecurePathError, match="protocol"):
        secure_path._read_message(connection)


@pytest.mark.parametrize(
    "payload",
    [
        b"\x00\x01",
        b"\x00\x01" + struct.pack("!i", -2),
        b"\x00\x01" + struct.pack("!i", 5) + b"ab",
        b"\x00\x01" + struct.pack("!i", 1) + b"\xff",
        struct.pack("!H", 65),
    ],
)
def test_bootstrap_rejects_invalid_data_row_structure(payload: bytes) -> None:
    connection = FakeBootstrapSocket(_backend_message(b"D", payload))

    with pytest.raises(secure_path.SecurePathError, match="DataRow"):
        secure_path._query(connection, "SELECT 1", expected_command="select")


def test_bootstrap_rejects_ready_before_authentication() -> None:
    connection = FakeBootstrapSocket(_backend_message(b"Z", b"I"))

    with pytest.raises(secure_path.SecurePathError, match="authentication"):
        secure_path._perform_bootstrap(connection, "atlas", "atlas")


def test_bootstrap_rejects_invalid_ready_state_after_authentication() -> None:
    connection = FakeBootstrapSocket(
        _backend_message(b"R", struct.pack("!I", 0)) + _backend_message(b"Z", b"X")
    )

    with pytest.raises(secure_path.SecurePathError, match="ReadyForQuery"):
        secure_path._perform_bootstrap(connection, "atlas", "atlas")


@pytest.mark.parametrize("transaction_state", [b"T", b"E"])
def test_bootstrap_requires_idle_ready_after_authentication(
    transaction_state: bytes,
) -> None:
    connection = FakeBootstrapSocket(
        _backend_message(b"R", struct.pack("!I", 0)) + _backend_message(b"Z", transaction_state)
    )

    with pytest.raises(secure_path.SecurePathError, match="idle"):
        secure_path._perform_bootstrap(connection, "atlas", "atlas")


def test_select_rejects_data_row_without_description() -> None:
    connection = FakeBootstrapSocket(
        _backend_message(b"D", _data_row([b"1"]))
        + _backend_message(b"C", b"SELECT 1\0")
        + _backend_message(b"Z", b"I")
    )

    with pytest.raises(secure_path.SecurePathError, match="RowDescription"):
        secure_path._query(connection, "SELECT 1", expected_command="select")


def test_select_rejects_data_row_column_mismatch() -> None:
    connection = FakeBootstrapSocket(
        _backend_message(b"T", _row_description(1))
        + _backend_message(b"D", _data_row([b"1", b"2"]))
    )

    with pytest.raises(secure_path.SecurePathError, match="column count"):
        secure_path._query(connection, "SELECT 1", expected_command="select")


def test_select_rejects_unexpected_result_value() -> None:
    connection = FakeBootstrapSocket(
        _backend_message(b"T", _row_description(1))
        + _backend_message(b"D", _data_row([b"unexpected"]))
    )

    with pytest.raises(secure_path.SecurePathError, match="result value"):
        secure_path._query(connection, "SELECT 1", expected_command="select")


@pytest.mark.parametrize(
    "messages",
    [
        _backend_message(b"T", _row_description(1))
        + _backend_message(b"C", b"SELECT 0\0")
        + _backend_message(b"C", b"SELECT 0\0"),
        _backend_message(b"T", _row_description(1)) + _backend_message(b"C", b"UPDATE 9\0"),
    ],
)
def test_select_rejects_duplicate_or_arbitrary_completion(messages: bytes) -> None:
    connection = FakeBootstrapSocket(messages)

    with pytest.raises(secure_path.SecurePathError, match="CommandComplete"):
        secure_path._query(connection, "SELECT 1", expected_command="select")


def test_select_rejects_row_after_completion() -> None:
    connection = FakeBootstrapSocket(
        _backend_message(b"T", _row_description(1))
        + _backend_message(b"C", b"SELECT 0\0")
        + _backend_message(b"D", _data_row([b"1"]))
    )

    with pytest.raises(secure_path.SecurePathError, match="completion"):
        secure_path._query(connection, "SELECT 1", expected_command="select")


def test_select_rejects_duplicate_data_row() -> None:
    row = _backend_message(b"D", _data_row([b"1"]))
    connection = FakeBootstrapSocket(_backend_message(b"T", _row_description(1)) + row + row)

    with pytest.raises(secure_path.SecurePathError, match="too many rows"):
        secure_path._query(connection, "SELECT 1", expected_command="select")


def test_select_rejects_duplicate_row_description() -> None:
    description = _backend_message(b"T", _row_description(1))
    connection = FakeBootstrapSocket(description + description)

    with pytest.raises(secure_path.SecurePathError, match="RowDescription"):
        secure_path._query(connection, "SELECT 1", expected_command="select")


@pytest.mark.parametrize("transaction_state", [b"T", b"E"])
def test_select_requires_idle_ready_after_completion(transaction_state: bytes) -> None:
    connection = FakeBootstrapSocket(
        _backend_message(b"T", _row_description(1))
        + _backend_message(b"C", b"SELECT 0\0")
        + _backend_message(b"Z", transaction_state)
    )

    with pytest.raises(secure_path.SecurePathError, match="idle"):
        secure_path._query(connection, "SELECT 1", expected_command="select")


def test_select_rejects_ready_before_completion() -> None:
    connection = FakeBootstrapSocket(
        _backend_message(b"T", _row_description(1)) + _backend_message(b"Z", b"I")
    )

    with pytest.raises(secure_path.SecurePathError, match="before command completion"):
        secure_path._query(connection, "SELECT 1", expected_command="select")


def test_select_allows_structurally_valid_notice_without_changing_state() -> None:
    connection = FakeBootstrapSocket(
        _backend_message(b"N", b"Mnotice\0\0")
        + _backend_message(b"T", _row_description(1))
        + _backend_message(b"C", b"SELECT 0\0")
        + _backend_message(b"N", b"Mnotice\0\0")
        + _backend_message(b"Z", b"I")
    )

    assert secure_path._query(connection, "SELECT 1", expected_command="select") == []


def test_select_rejects_malformed_notice() -> None:
    connection = FakeBootstrapSocket(_backend_message(b"N", b"unterminated"))

    with pytest.raises(secure_path.SecurePathError, match="ErrorResponse"):
        secure_path._query(connection, "SELECT 1", expected_command="select")


def test_create_database_rejects_row_description_and_data() -> None:
    for messages in (
        _backend_message(b"T", _row_description(1)),
        _backend_message(b"D", _data_row([b"1"])),
    ):
        connection = FakeBootstrapSocket(messages)

        with pytest.raises(secure_path.SecurePathError, match="CREATE DATABASE"):
            secure_path._query(
                connection,
                'CREATE DATABASE "atlas"',
                expected_command="create_database",
            )


def test_create_database_rejects_arbitrary_completion() -> None:
    connection = FakeBootstrapSocket(
        _backend_message(b"C", b"CREATE TABLE\0") + _backend_message(b"Z", b"I")
    )

    with pytest.raises(secure_path.SecurePathError, match="CommandComplete"):
        secure_path._query(
            connection,
            'CREATE DATABASE "atlas"',
            expected_command="create_database",
        )


def test_bootstrap_handles_error_response_as_stable_domain_error() -> None:
    connection = FakeBootstrapSocket(_backend_message(b"E", b"Mdenied\0\0"))

    with pytest.raises(secure_path.SecurePathError, match="server rejected"):
        secure_path._perform_bootstrap(connection, "atlas", "atlas")


def test_bootstrap_timeout_becomes_stable_domain_error() -> None:
    connection = FakeBootstrapSocket(timeout_on_recv=True)

    with pytest.raises(secure_path.SecurePathError, match="timed out"):
        secure_path._read_message(connection)


def test_bootstrap_cli_never_leaks_traceback_for_runtime_failure() -> None:
    result = subprocess.run(
        ["/usr/bin/python3", "infra/local/secure_path.py", "bootstrap", "atlas", "atlas"],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "RSI_ATLAS_BOUND_POSTGRES_FD": "999999"},
    )

    assert result.returncode == 1
    assert result.stderr == (
        "Secure PostgreSQL bootstrap failed: PostgreSQL bootstrap protocol failure\n"
    )
    assert "Traceback" not in result.stderr


def test_postmaster_and_backend_do_not_retain_bound_directory_fd(
    postgres_database: PostgresDatabase,
) -> None:
    postgres_root = postgres_database.settings.socket_directory.parent
    postmaster_pid = int((postgres_root / "data" / "postmaster.pid").read_text().splitlines()[0])
    with postgres_database.connect() as connection:
        backend_pid = connection.execute("SELECT pg_backend_pid()").fetchone()
        assert backend_pid is not None

        for process_id in (postmaster_pid, backend_pid[0]):
            output = subprocess.run(
                ["lsof", "-a", "-p", str(process_id), "-d", "3-999", "-Fftn"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            records = output.split("f")[1:]
            retained_directories = {
                line[1:]
                for record in records
                if "\ntDIR\n" in f"\n{record}"
                for line in record.splitlines()
                if line.startswith("n")
            }
            assert str(postgres_root) not in retained_directories


def test_registration_round_trip(postgres_database: PostgresDatabase, tmp_path: Path) -> None:
    context = _context()
    artifact_store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    descriptor = artifact_store.put_bytes(
        b"restart evidence", media_type="application/pdf", context=context
    )
    repository = ArtifactRepository(postgres_database, artifact_store)

    repository.register(context=context, descriptor=descriptor)

    assert repository.find(context=context, artifact_id=descriptor.artifact_id) == descriptor
