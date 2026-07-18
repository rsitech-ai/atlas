import os
from pathlib import Path

import pytest
from psycopg.conninfo import conninfo_to_dict
from rsi_atlas_storage.database import DatabaseSettings


def test_database_settings_accept_owner_only_absolute_socket(tmp_path: Path) -> None:
    socket_directory = tmp_path / "socket"
    socket_directory.mkdir(mode=0o700)

    settings = DatabaseSettings.from_conninfo(f"host={socket_directory} user=atlas dbname=atlas")

    assert settings.socket_directory == socket_directory
    assert settings.user == "atlas"
    assert settings.database == "atlas"
    assert settings.port == 5432
    assert conninfo_to_dict(settings.conninfo)["port"] == "5432"


def test_database_settings_apply_bounded_runtime_deadlines(tmp_path: Path) -> None:
    socket_directory = tmp_path / "socket"
    socket_directory.mkdir(mode=0o700)

    settings = DatabaseSettings.from_conninfo(
        f"host={socket_directory} user=atlas dbname=atlas options='-c statement_timeout=0'",
        connect_timeout_seconds=2,
        statement_timeout_ms=4_000,
        lock_timeout_ms=2_000,
        transaction_timeout_ms=5_000,
    )

    parsed = conninfo_to_dict(settings.conninfo)
    assert parsed["connect_timeout"] == "2"
    assert parsed["options"] == (
        "-c statement_timeout=4000 -c lock_timeout=2000 -c transaction_timeout=5000"
    )


@pytest.mark.parametrize(
    "conninfo",
    [
        "postgresql://atlas@127.0.0.1/atlas",
        "postgresql://atlas@localhost/atlas",
        "host=relative/socket user=atlas dbname=atlas",
        "user=atlas dbname=atlas",
    ],
)
def test_database_settings_reject_non_socket_hosts(conninfo: str) -> None:
    with pytest.raises(ValueError, match="Unix socket"):
        DatabaseSettings.from_conninfo(conninfo)


@pytest.mark.parametrize(
    "conninfo",
    [
        "service=remote",
        "service=remote servicefile=/tmp/pg_service.conf",
        "servicefile=/tmp/pg_service.conf host=/private/tmp user=atlas dbname=atlas",
    ],
)
def test_database_settings_rejects_libpq_service_configuration(conninfo: str) -> None:
    with pytest.raises(ValueError, match="service"):
        DatabaseSettings.from_conninfo(conninfo)


def test_database_settings_rejects_conflicting_socket_port(tmp_path: Path) -> None:
    socket_directory = tmp_path / "socket"
    socket_directory.mkdir(mode=0o700)

    with pytest.raises(ValueError, match="port 5432"):
        DatabaseSettings.from_conninfo(f"host={socket_directory} port=5433 user=atlas dbname=atlas")


def test_database_settings_rejects_ambient_pgport(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket_directory = tmp_path / "socket"
    socket_directory.mkdir(mode=0o700)
    settings = DatabaseSettings.from_conninfo(f"host={socket_directory} user=atlas dbname=atlas")
    monkeypatch.setenv("PGPORT", "5433")

    with pytest.raises(ValueError, match="PGPORT"):
        settings.assert_safe_environment()


def test_database_settings_requires_user_and_database(tmp_path: Path) -> None:
    socket_directory = tmp_path / "socket"
    socket_directory.mkdir(mode=0o700)

    with pytest.raises(ValueError, match="user"):
        DatabaseSettings.from_conninfo(f"host={socket_directory} dbname=atlas")
    with pytest.raises(ValueError, match="database"):
        DatabaseSettings.from_conninfo(f"host={socket_directory} user=atlas")


def test_database_settings_rejects_group_or_world_accessible_socket(tmp_path: Path) -> None:
    socket_directory = tmp_path / "socket"
    socket_directory.mkdir(mode=0o700)
    socket_directory.chmod(0o750)

    with pytest.raises(ValueError, match="owner-only"):
        DatabaseSettings.from_conninfo(f"host={socket_directory} user=atlas dbname=atlas")


def test_database_settings_rejects_socket_not_owned_by_current_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    socket_directory = tmp_path / "socket"
    socket_directory.mkdir(mode=0o700)
    actual_stat = socket_directory.stat()

    class ForeignOwnerStat:
        st_mode = actual_stat.st_mode
        st_uid = os.getuid() + 1

    monkeypatch.setattr(Path, "stat", lambda _path, **_kwargs: ForeignOwnerStat())

    with pytest.raises(ValueError, match="current user"):
        DatabaseSettings.from_conninfo(f"host={socket_directory} user=atlas dbname=atlas")


def test_database_settings_rejects_symlink_in_socket_ancestor(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(outside, target_is_directory=True)
    socket_directory = linked_parent / "socket"
    socket_directory.mkdir(mode=0o700)

    with pytest.raises(ValueError, match="symlink"):
        DatabaseSettings.from_conninfo(f"host={socket_directory} user=atlas dbname=atlas")
