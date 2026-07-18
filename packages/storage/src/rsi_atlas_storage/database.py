import os
import re
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
_SERVICE_PARAMETER = re.compile(r"(?:^|[?&\s])(service|servicefile)\s*=", re.IGNORECASE)
_UNSAFE_LIBPQ_ENVIRONMENT = ("PGSERVICE", "PGSERVICEFILE", "PGHOSTADDR")


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    conninfo: str
    socket_directory: Path
    user: str
    database: str

    @classmethod
    def from_conninfo(
        cls,
        conninfo: str,
        *,
        connect_timeout_seconds: int | None = None,
        statement_timeout_ms: int | None = None,
        lock_timeout_ms: int | None = None,
    ) -> "DatabaseSettings":
        if _SERVICE_PARAMETER.search(conninfo):
            raise ValueError("libpq service and servicefile configuration is forbidden")
        parsed = conninfo_to_dict(conninfo)
        if parsed.get("service"):
            raise ValueError("libpq service configuration is forbidden")
        raw_host = parsed.get("host")
        if (
            not isinstance(raw_host, str)
            or not raw_host
            or "," in raw_host
            or parsed.get("hostaddr")
            or not Path(raw_host).is_absolute()
        ):
            raise ValueError("RSI Atlas PostgreSQL must use one absolute Unix socket directory")
        raw_user = parsed.get("user")
        if not isinstance(raw_user, str) or not raw_user:
            raise ValueError("RSI Atlas PostgreSQL requires an explicit user")
        raw_database = parsed.get("dbname")
        if not isinstance(raw_database, str) or not raw_database:
            raise ValueError("RSI Atlas PostgreSQL requires an explicit database")
        cls._apply_runtime_deadlines(
            parsed,
            connect_timeout_seconds=connect_timeout_seconds,
            statement_timeout_ms=statement_timeout_ms,
            lock_timeout_ms=lock_timeout_ms,
        )
        socket_directory = Path(raw_host)
        cls._validate_socket_directory(socket_directory)
        return cls(
            conninfo=make_conninfo("", **parsed),
            socket_directory=socket_directory,
            user=raw_user,
            database=raw_database,
        )

    @staticmethod
    def _apply_runtime_deadlines(
        parsed: dict[str, str | int | None],
        *,
        connect_timeout_seconds: int | None,
        statement_timeout_ms: int | None,
        lock_timeout_ms: int | None,
    ) -> None:
        configured = (
            connect_timeout_seconds,
            statement_timeout_ms,
            lock_timeout_ms,
        )
        if all(value is None for value in configured):
            return
        if (
            type(connect_timeout_seconds) is not int
            or not 1 <= connect_timeout_seconds <= 30
            or type(statement_timeout_ms) is not int
            or not 1 <= statement_timeout_ms <= 60_000
            or type(lock_timeout_ms) is not int
            or not 1 <= lock_timeout_ms <= 60_000
        ):
            raise ValueError("runtime database deadlines are invalid")
        parsed["connect_timeout"] = str(connect_timeout_seconds)
        parsed["options"] = (
            f"-c statement_timeout={statement_timeout_ms} -c lock_timeout={lock_timeout_ms}"
        )

    def assert_safe_environment(self) -> None:
        unsafe = [name for name in _UNSAFE_LIBPQ_ENVIRONMENT if os.environ.get(name)]
        if unsafe:
            joined = ", ".join(unsafe)
            raise ValueError(f"unsafe libpq environment is forbidden: {joined}")
        self._validate_socket_directory(self.socket_directory)

    @classmethod
    def _validate_socket_directory(cls, socket_directory: Path) -> None:
        cls._reject_symlink_chain(socket_directory)
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

    @staticmethod
    def _reject_symlink_chain(path: Path) -> None:
        current = Path(path.anchor)
        for component in path.parts[1:]:
            current /= component
            try:
                component_stat = current.lstat()
            except FileNotFoundError:
                break
            if stat.S_ISLNK(component_stat.st_mode):
                raise ValueError(
                    f"PostgreSQL Unix socket path must not contain a symlink: {current}"
                )


class PostgresDatabase:
    def __init__(self, settings: DatabaseSettings) -> None:
        self.settings = settings

    @contextmanager
    def connect(self, *, autocommit: bool = False) -> Iterator[Connection[Row]]:
        self.settings.assert_safe_environment()
        with psycopg.connect(self.settings.conninfo, autocommit=autocommit) as connection:
            yield connection

    def fetch_value(self, query: str, parameters: Sequence[ParameterValue] | None = None) -> Any:
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
