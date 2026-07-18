#!/usr/bin/python3
"""Create RSI Atlas PostgreSQL roots without following filesystem symlinks."""

import errno
import os
import re
import socket
import stat
import struct
import sys
from pathlib import Path
from typing import Optional

PRIVATE_MODE = 0o700
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
DATABASE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


class SecurePathError(RuntimeError):
    pass


class SecurePathMissing(RuntimeError):
    pass


def _open_child(parent_fd: int, name: str, *, create: bool) -> int:
    try:
        return os.open(name, DIRECTORY_FLAGS, dir_fd=parent_fd)
    except FileNotFoundError as error:
        if not create:
            raise SecurePathMissing(name) from error
        os.mkdir(name, mode=PRIVATE_MODE, dir_fd=parent_fd)
        return os.open(name, DIRECTORY_FLAGS, dir_fd=parent_fd)
    except OSError as error:
        if error.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise SecurePathError(f"path contains a symlink or non-directory: {name}") from error
        raise


def _open_absolute_directory(path: Path, *, create: bool) -> int:
    if not path.is_absolute():
        raise SecurePathError("RSI_ATLAS_DATA_ROOT must be an absolute path")
    current_fd = os.open("/", DIRECTORY_FLAGS)
    try:
        for component in path.parts[1:]:
            child_fd = _open_child(current_fd, component, create=create)
            os.close(current_fd)
            current_fd = child_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _require_current_owner(directory_fd: int, label: str) -> None:
    directory_stat = os.fstat(directory_fd)
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise SecurePathError(f"{label} must be a directory")
    if directory_stat.st_uid != os.getuid():
        raise SecurePathError(f"{label} must be owned by the current user")
    os.fchmod(directory_fd, PRIVATE_MODE)


def _open_validated_postgres(data_root: Path, *, create: bool) -> int:
    data_root_fd = _open_absolute_directory(data_root, create=create)
    try:
        postgres_fd = _open_child(data_root_fd, "postgres", create=create)
    finally:
        os.close(data_root_fd)
    try:
        _require_current_owner(postgres_fd, "PostgreSQL root")
        socket_fd = _open_child(postgres_fd, "socket", create=create)
        try:
            _require_current_owner(socket_fd, "PostgreSQL socket root")
        finally:
            os.close(socket_fd)
        try:
            data_fd = _open_child(postgres_fd, "data", create=False)
        except SecurePathMissing:
            if not create:
                raise
        else:
            try:
                _require_current_owner(data_fd, "PostgreSQL data root")
            finally:
                os.close(data_fd)
        return postgres_fd
    except BaseException:
        os.close(postgres_fd)
        raise


def execute_bound(data_root: Path, *, create: bool, command: list[str]) -> None:
    if not command:
        raise SecurePathError("bound execution requires a command")
    postgres_fd = _open_validated_postgres(data_root, create=create)
    try:
        postgres_stat = os.fstat(postgres_fd)
        os.fchdir(postgres_fd)
        cwd_stat = os.stat(".", follow_symlinks=False)
        if (cwd_stat.st_dev, cwd_stat.st_ino) != (
            postgres_stat.st_dev,
            postgres_stat.st_ino,
        ):
            raise SecurePathError("bound PostgreSQL directory identity changed")
        environment = {
            **os.environ,
            "RSI_ATLAS_BOUND_POSTGRES": "1",
            "RSI_ATLAS_BOUND_DEVICE": str(postgres_stat.st_dev),
            "RSI_ATLAS_BOUND_INODE": str(postgres_stat.st_ino),
            "RSI_ATLAS_BOUND_FD": str(postgres_fd),
        }
        os.set_inheritable(postgres_fd, True)
        os.execvpe(command[0], command, environment)
    finally:
        os.close(postgres_fd)


def _read_exact(connection: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = connection.recv(remaining)
        if not chunk:
            raise SecurePathError("PostgreSQL bootstrap connection closed unexpectedly")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_message(connection: socket.socket) -> tuple[bytes, bytes]:
    message_type = _read_exact(connection, 1)
    message_length = struct.unpack("!I", _read_exact(connection, 4))[0]
    if message_length < 4:
        raise SecurePathError("PostgreSQL bootstrap returned an invalid message")
    return message_type, _read_exact(connection, message_length - 4)


def _database_error(payload: bytes) -> SecurePathError:
    fields = payload.rstrip(b"\0").split(b"\0")
    messages = [field[1:].decode("utf-8", "replace") for field in fields if field[:1] == b"M"]
    detail = messages[0] if messages else "unknown PostgreSQL error"
    return SecurePathError(f"PostgreSQL bootstrap failed: {detail}")


def _query(
    connection: socket.socket, query: str
) -> list[tuple[Optional[str], ...]]:  # noqa: UP045 - macOS system Python 3.9
    query_payload = query.encode("utf-8") + b"\0"
    connection.sendall(b"Q" + struct.pack("!I", len(query_payload) + 4) + query_payload)
    rows: list[tuple[Optional[str], ...]] = []  # noqa: UP045
    while True:
        message_type, payload = _read_message(connection)
        if message_type == b"D":
            column_count = struct.unpack("!H", payload[:2])[0]
            offset = 2
            columns: list[Optional[str]] = []  # noqa: UP045
            for _ in range(column_count):
                value_length = struct.unpack("!i", payload[offset : offset + 4])[0]
                offset += 4
                if value_length == -1:
                    columns.append(None)
                    continue
                value = payload[offset : offset + value_length]
                offset += value_length
                columns.append(value.decode("utf-8"))
            rows.append(tuple(columns))
        elif message_type == b"E":
            raise _database_error(payload)
        elif message_type == b"Z":
            return rows


def bootstrap_database(user: str, database: str) -> None:
    if not DATABASE_IDENTIFIER.fullmatch(user) or not DATABASE_IDENTIFIER.fullmatch(database):
        raise SecurePathError("PostgreSQL bootstrap identifiers are invalid")
    bound_fd_text = os.environ.get("RSI_ATLAS_BOUND_FD", "")
    if not bound_fd_text.isdigit():
        raise SecurePathError("PostgreSQL bootstrap requires a bound directory descriptor")
    bound_stat = os.fstat(int(bound_fd_text))
    cwd_stat = os.stat(".", follow_symlinks=False)
    if (bound_stat.st_dev, bound_stat.st_ino) != (cwd_stat.st_dev, cwd_stat.st_ino):
        raise SecurePathError("PostgreSQL bootstrap directory identity changed")

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect("socket/.s.PGSQL.5432")
        parameters = (
            b"user\0" + user.encode("ascii") + b"\0database\0postgres\0client_encoding\0UTF8\0\0"
        )
        startup = struct.pack("!I", 196608) + parameters
        connection.sendall(struct.pack("!I", len(startup) + 4) + startup)
        while True:
            message_type, payload = _read_message(connection)
            if message_type == b"R" and struct.unpack("!I", payload[:4])[0] != 0:
                raise SecurePathError("PostgreSQL bootstrap requires local trust authentication")
            if message_type == b"E":
                raise _database_error(payload)
            if message_type == b"Z":
                break
        rows = _query(
            connection,
            f"SELECT 1 FROM pg_database WHERE datname = '{database}'",
        )
        if not rows:
            _query(connection, f'CREATE DATABASE "{database}"')
        connection.sendall(b"X" + struct.pack("!I", 4))


def main() -> int:
    if len(sys.argv) == 4 and sys.argv[1] == "bootstrap":
        try:
            bootstrap_database(sys.argv[2], sys.argv[3])
        except (OSError, SecurePathError) as error:
            print(f"Secure PostgreSQL bootstrap failed: {error}", file=sys.stderr)
            return 1
        return 0
    if (
        len(sys.argv) < 6
        or sys.argv[1] != "exec"
        or sys.argv[2] not in {"prepare", "inspect"}
        or sys.argv[4] != "--"
    ):
        print(
            f"usage: {sys.argv[0]} exec {{prepare|inspect}} DATA_ROOT -- COMMAND...",
            file=sys.stderr,
        )
        return 2
    try:
        execute_bound(
            Path(sys.argv[3]),
            create=sys.argv[2] == "prepare",
            command=sys.argv[5:],
        )
    except SecurePathMissing:
        return 3
    except (OSError, SecurePathError) as error:
        print(f"Secure PostgreSQL path rejected: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
