"""Release-native lifecycle for the bundled PostgreSQL and pgvector runtime."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Protocol

_OWNER_SCHEMA = "rsi-atlas.embedded-postgres-owner.v1"


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
    _lock_descriptor: int | None = field(default=None, init=False, repr=False)

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
    def ownership_path(self) -> Path:
        return self.postgres_root / "owner.json"

    @property
    def ownership_lock_path(self) -> Path:
        return self.postgres_root / "owner.lock"

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

    def _acquire_ownership_lock(self) -> None:
        if self._lock_descriptor is not None:
            raise RuntimeError("PostgreSQL ownership lock is already held")
        flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
        descriptor = os.open(self.ownership_lock_path, flags, 0o600)
        try:
            metadata = os.fstat(descriptor)
            if (
                metadata.st_uid != os.getuid()
                or not stat.S_ISREG(metadata.st_mode)
                or stat.S_IMODE(metadata.st_mode) != 0o600
            ):
                raise ValueError("PostgreSQL ownership lock must be owner-private")
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            os.close(descriptor)
            raise
        self._lock_descriptor = descriptor

    def _release_ownership_lock(self) -> None:
        if self._lock_descriptor is None:
            return
        os.close(self._lock_descriptor)
        self._lock_descriptor = None

    def _owner_base(self) -> dict[str, object]:
        executable = self._executables["postgres"]
        return {
            "data_directory": str(self.data_directory.resolve(strict=False)),
            "postgres_sha256": sha256(executable.read_bytes()).hexdigest(),
            "schema_version": _OWNER_SCHEMA,
            "socket_directory": str(self.socket_directory.resolve(strict=False)),
        }

    def _write_owner(
        self,
        *,
        state: str,
        postmaster_pid: int | None = None,
        postmaster_started_at: int | None = None,
    ) -> None:
        document = {
            **self._owner_base(),
            "postmaster_pid": postmaster_pid,
            "postmaster_started_at": postmaster_started_at,
            "state": state,
        }
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".owner.",
            suffix=".tmp",
            dir=self.postgres_root,
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            payload = (
                json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                + "\n"
            ).encode("utf-8")
            remaining = memoryview(payload)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("failed to write PostgreSQL owner record")
                remaining = remaining[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.replace(temporary, self.ownership_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _read_owner(self) -> dict[str, object]:
        path = self.ownership_path
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("running PostgreSQL has no trusted RSI Atlas owner")
        metadata = path.stat(follow_symlinks=False)
        if (
            metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size > 4096
        ):
            raise RuntimeError("running PostgreSQL owner record is not trusted")
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise RuntimeError("running PostgreSQL owner record is invalid") from error
        if not isinstance(document, dict):
            raise RuntimeError("running PostgreSQL owner record is invalid")
        return document

    def _postmaster_identity(self) -> tuple[int, int]:
        path = self.data_directory / "postmaster.pid"
        try:
            metadata = path.stat(follow_symlinks=False)
        except OSError as error:
            raise RuntimeError("running PostgreSQL postmaster identity is invalid") from error
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or metadata.st_size > 4096
        ):
            raise RuntimeError("running PostgreSQL postmaster identity is invalid")
        lines = path.read_text(encoding="utf-8").splitlines()
        try:
            pid = int(lines[0])
            data_directory = Path(lines[1]).resolve(strict=True)
            started_at = int(lines[2])
            port = int(lines[3])
            socket_directory = Path(lines[4]).resolve(strict=True)
        except (IndexError, OSError, ValueError) as error:
            raise RuntimeError("running PostgreSQL postmaster identity is invalid") from error
        if (
            pid <= 1
            or data_directory != self.data_directory.resolve(strict=True)
            or port != 5432
            or socket_directory != self.socket_directory.resolve(strict=True)
        ):
            raise RuntimeError("running PostgreSQL postmaster identity does not match")
        return pid, started_at

    def _recover_owned_orphan(self) -> None:
        owner = self._read_owner()
        pid, started_at = self._postmaster_identity()
        expected = self._owner_base()
        if any(owner.get(key) != value for key, value in expected.items()):
            raise RuntimeError("running PostgreSQL belongs to another runtime")
        state = owner.get("state")
        if state not in {"starting", "running"}:
            raise RuntimeError("running PostgreSQL owner state is invalid")
        if state == "running" and (
            owner.get("postmaster_pid") != pid or owner.get("postmaster_started_at") != started_at
        ):
            raise RuntimeError("running PostgreSQL owner identity changed")
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
        if self._is_running():
            raise RuntimeError("owned PostgreSQL orphan did not stop")
        self.ownership_path.unlink(missing_ok=True)

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
        self._acquire_ownership_lock()
        try:
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
            control = self._run(
                [str(self._executables["pg_controldata"]), str(self.data_directory)]
            )
            checksum_lines = [
                line.partition(":")[2].strip()
                for line in control.stdout.splitlines()
                if line.startswith("Data page checksum version:")
            ]
            if checksum_lines != ["1"]:
                raise RuntimeError("PostgreSQL data checksums are not enabled")
            if self._is_running():
                self._recover_owned_orphan()
            self._write_owner(state="starting")
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
            postmaster_pid, postmaster_started_at = self._postmaster_identity()
            self._write_owner(
                state="running",
                postmaster_pid=postmaster_pid,
                postmaster_started_at=postmaster_started_at,
            )
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
            if self._started_here:
                self.stop()
            else:
                self._release_ownership_lock()
            raise

    def stop(self) -> None:
        try:
            if self._started_here:
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
                self.ownership_path.unlink(missing_ok=True)
        finally:
            self._release_ownership_lock()


__all__ = ["EmbeddedPostgres"]
