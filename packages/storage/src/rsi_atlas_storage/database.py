import os
import stat
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from psycopg import Connection
from psycopg.conninfo import conninfo_to_dict, make_conninfo

Row = tuple[Any, ...]
ParameterValue = object


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    conninfo: str
    socket_directory: Path
    user: str
    database: str

    @classmethod
    def from_conninfo(cls, conninfo: str) -> "DatabaseSettings":
        parsed = conninfo_to_dict(conninfo)
        raw_host = parsed.get("host")
        if (
            not isinstance(raw_host, str)
            or not raw_host
            or "," in raw_host
            or parsed.get("hostaddr")
            or not Path(raw_host).is_absolute()
        ):
            raise ValueError(
                "RSI Atlas PostgreSQL must use one absolute Unix socket directory"
            )
        raw_user = parsed.get("user")
        if not isinstance(raw_user, str) or not raw_user:
            raise ValueError("RSI Atlas PostgreSQL requires an explicit user")
        raw_database = parsed.get("dbname")
        if not isinstance(raw_database, str) or not raw_database:
            raise ValueError("RSI Atlas PostgreSQL requires an explicit database")
        socket_directory = Path(raw_host)
        try:
            socket_stat = socket_directory.stat(follow_symlinks=False)
        except (FileNotFoundError, NotADirectoryError) as error:
            raise ValueError("PostgreSQL Unix socket directory does not exist") from error
        if not stat.S_ISDIR(socket_stat.st_mode):
            raise ValueError("PostgreSQL Unix socket path must be a directory")
        if socket_stat.st_uid != os.getuid():
            raise ValueError("PostgreSQL Unix socket directory must be owned by current user")
        if stat.S_IMODE(socket_stat.st_mode) & 0o077:
            raise ValueError("PostgreSQL Unix socket directory must be owner-only")
        return cls(
            conninfo=make_conninfo("", **parsed),
            socket_directory=socket_directory,
            user=raw_user,
            database=raw_database,
        )


class PostgresDatabase:
    def __init__(self, settings: DatabaseSettings) -> None:
        self.settings = settings

    @contextmanager
    def connect(self, *, autocommit: bool = False) -> Iterator[Connection[Row]]:
        with psycopg.connect(self.settings.conninfo, autocommit=autocommit) as connection:
            yield connection

    def fetch_value(
        self, query: str, parameters: Sequence[ParameterValue] | None = None
    ) -> Any:
        with self.connect(autocommit=True) as connection, connection.cursor() as cursor:
            cursor.execute(query, parameters)
            row = cursor.fetchone()
        return None if row is None else row[0]

    def fetch_one(
        self, query: str, parameters: Sequence[ParameterValue] | None = None
    ) -> Row | None:
        with self.connect(autocommit=True) as connection, connection.cursor() as cursor:
            cursor.execute(query, parameters)
            return cursor.fetchone()
