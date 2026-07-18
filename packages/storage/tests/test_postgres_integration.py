import os
import shutil
import stat
import subprocess
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
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
    assert postgres_database.fetch_value("SELECT count(*) FROM atlas_meta.schema_migrations") == 1


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


def test_registration_round_trip(
    postgres_database: PostgresDatabase, tmp_path: Path
) -> None:
    context = _context()
    artifact_store = ContentAddressedArtifactStore(tmp_path / "artifacts")
    descriptor = artifact_store.put_bytes(
        b"restart evidence", media_type="application/pdf", context=context
    )
    repository = ArtifactRepository(postgres_database, artifact_store)

    repository.register(context=context, descriptor=descriptor)

    assert repository.find(context=context, artifact_id=descriptor.artifact_id) == descriptor
