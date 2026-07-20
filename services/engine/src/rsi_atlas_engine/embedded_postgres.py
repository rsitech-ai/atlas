"""Release-native lifecycle for the bundled PostgreSQL and pgvector runtime."""

from __future__ import annotations

import os
import stat
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class CommandRunner(Protocol):
    def __call__(
        self,
        arguments: Sequence[str],
        *,
        environment: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]: ...


def _run_command(
    arguments: Sequence[str],
    *,
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )


@dataclass(slots=True)
class EmbeddedPostgres:
    runtime_root: Path
    data_root: Path
    runner: CommandRunner = field(default=_run_command, repr=False)
    _started_here: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.runtime_root = self.runtime_root.resolve(strict=False)
        self.data_root = self.data_root.resolve(strict=False)
        if not self.data_root.is_dir():
            raise ValueError("PostgreSQL data root must already exist")
        metadata = self.data_root.stat()
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise ValueError("PostgreSQL data root must be owner-private")
        for executable in self._executables.values():
            if not executable.is_file() or not os.access(executable, os.X_OK):
                raise ValueError("bundled PostgreSQL executable is missing")
        required = (
            self.postgresql_root / "share" / "postgresql@17" / "extension" / "vector.control",
            self.postgresql_root / "lib" / "postgresql" / "vector.dylib",
        )
        if any(path.is_symlink() or not path.is_file() for path in required):
            raise ValueError("bundled pgvector resources are missing")

    @property
    def postgresql_root(self) -> Path:
        return self.runtime_root / "postgresql"

    @property
    def postgres_root(self) -> Path:
        return self.data_root / "postgres"

    @property
    def data_directory(self) -> Path:
        return self.postgres_root / "data"

    @property
    def socket_directory(self) -> Path:
        return self.postgres_root / "socket"

    @property
    def _executables(self) -> dict[str, Path]:
        binary_root = self.postgresql_root / "bin"
        return {
            name: binary_root / name
            for name in ("createdb", "initdb", "pg_controldata", "pg_ctl", "postgres", "psql")
        }

    def _environment(self) -> dict[str, str]:
        temporary = self.postgres_root / "tmp"
        return {
            "HOME": str(self.data_root),
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
            "PGDATABASE": "atlas",
            "PGHOST": str(self.socket_directory),
            "PGPORT": "5432",
            "PGUSER": "atlas",
            "TMPDIR": str(temporary),
        }

    def _run(
        self,
        arguments: Sequence[str],
        *,
        allowed: frozenset[int] = frozenset({0}),
    ) -> subprocess.CompletedProcess[str]:
        result = self.runner(arguments, environment=self._environment())
        if result.returncode not in allowed:
            raise RuntimeError(f"bundled PostgreSQL command failed: {Path(arguments[0]).name}")
        return result

    def _prepare_directories(self) -> None:
        self.postgres_root.mkdir(mode=0o700, exist_ok=True)
        for directory in (self.socket_directory, self.postgres_root / "tmp"):
            directory.mkdir(mode=0o700, exist_ok=True)
            if directory.is_symlink() or stat.S_IMODE(directory.stat().st_mode) != 0o700:
                raise ValueError("PostgreSQL runtime directory must be owner-private")

    def _is_running(self) -> bool:
        if not (self.data_directory / "PG_VERSION").is_file():
            return False
        result = self._run(
            [str(self._executables["pg_ctl"]), "--pgdata", str(self.data_directory), "status"],
            allowed=frozenset({0, 3}),
        )
        return result.returncode == 0

    def start(self) -> None:
        self._prepare_directories()
        if not (self.data_directory / "PG_VERSION").is_file():
            self._run(
                [
                    str(self._executables["initdb"]),
                    f"--pgdata={self.data_directory}",
                    "--username=atlas",
                    "--auth-local=trust",
                    "--auth-host=reject",
                    "--encoding=UTF8",
                    "--no-locale",
                    "--data-checksums",
                ]
            )
        control = self._run([str(self._executables["pg_controldata"]), str(self.data_directory)])
        checksum_lines = [
            line.partition(":")[2].strip()
            for line in control.stdout.splitlines()
            if line.startswith("Data page checksum version:")
        ]
        if checksum_lines != ["1"]:
            raise RuntimeError("PostgreSQL data checksums are not enabled")
        if self._is_running():
            raise RuntimeError("PostgreSQL cluster is already owned by another process")
        options = " ".join(
            (
                "-c listen_addresses=''",
                f"-c unix_socket_directories='{self.socket_directory}'",
                "-c unix_socket_permissions=0700",
            )
        )
        self._run(
            [
                str(self._executables["pg_ctl"]),
                "--pgdata",
                str(self.data_directory),
                "--log",
                str(self.postgres_root / "postgres.log"),
                "--options",
                options,
                "--wait",
                "start",
            ]
        )
        self._started_here = True
        try:
            database = self._run(
                [
                    str(self._executables["psql"]),
                    "--dbname=postgres",
                    "--tuples-only",
                    "--no-align",
                    "--command",
                    "SELECT 1 FROM pg_database WHERE datname='atlas'",
                ]
            )
            if database.stdout.strip() != "1":
                self._run(
                    [
                        str(self._executables["createdb"]),
                        "--maintenance-db=postgres",
                        "atlas",
                    ]
                )
            self._run(
                [
                    str(self._executables["psql"]),
                    "--dbname=atlas",
                    "--set=ON_ERROR_STOP=1",
                    "--command",
                    "CREATE EXTENSION IF NOT EXISTS vector",
                ]
            )
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        if not self._started_here:
            return
        self._run(
            [
                str(self._executables["pg_ctl"]),
                "--pgdata",
                str(self.data_directory),
                "--mode=fast",
                "--wait",
                "stop",
            ]
        )
        self._started_here = False


__all__ = ["EmbeddedPostgres"]
