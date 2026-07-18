import os
from pathlib import Path

import pytest
from rsi_atlas_storage.database import DatabaseSettings


def test_database_settings_accept_owner_only_absolute_socket(tmp_path: Path) -> None:
    socket_directory = tmp_path / "socket"
    socket_directory.mkdir(mode=0o700)

    settings = DatabaseSettings.from_conninfo(
        f"host={socket_directory} user=atlas dbname=atlas"
    )

    assert settings.socket_directory == socket_directory
    assert settings.user == "atlas"
    assert settings.database == "atlas"


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
        DatabaseSettings.from_conninfo(
            f"host={socket_directory} user=atlas dbname=atlas"
        )


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
        DatabaseSettings.from_conninfo(
            f"host={socket_directory} user=atlas dbname=atlas"
        )
