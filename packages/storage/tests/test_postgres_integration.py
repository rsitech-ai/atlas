import os
import shutil
import stat
import subprocess
import tempfile
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
    assert postgres_database.fetch_value("SHOW unix_socket_directories") == str(socket_directory)
    assert stat.S_IMODE(socket_directory.stat().st_mode) == 0o700
    data_directory = socket_directory.parent / "data"
    assert data_directory.is_absolute()
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


def test_registration_round_trip(postgres_database: PostgresDatabase, tmp_path: Path) -> None:
    context = _context()
    artifact_store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    descriptor = artifact_store.put_bytes(
        b"restart evidence", media_type="application/pdf", context=context
    )
    repository = ArtifactRepository(postgres_database, artifact_store)

    repository.register(context=context, descriptor=descriptor)

    assert repository.find(context=context, artifact_id=descriptor.artifact_id) == descriptor
