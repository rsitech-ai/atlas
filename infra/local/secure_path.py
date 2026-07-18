#!/usr/bin/python3
"""Create RSI Atlas PostgreSQL roots without following filesystem symlinks."""

import errno
import os
import re
import socket
import stat
import struct
import sys
import time
from pathlib import Path
from typing import Optional

PRIVATE_MODE = 0o700
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
DATABASE_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")
MAX_FRAME_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 2 * 1024 * 1024
MAX_MESSAGES = 256
MAX_ROWS = 32
MAX_COLUMNS = 64
MAX_VALUE_BYTES = 64 * 1024
BOOTSTRAP_TIMEOUT_SECONDS = 5.0
IO_TIMEOUT_SECONDS = 1.0


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
            "RSI_ATLAS_BOUND_POSTGRES_FD": str(postgres_fd),
        }
        os.set_inheritable(postgres_fd, True)
        os.execvpe(command[0], command, environment)
    finally:
        os.close(postgres_fd)


class ProtocolBudget:
    def __init__(self) -> None:
        self.deadline = time.monotonic() + BOOTSTRAP_TIMEOUT_SECONDS
        self.message_count = 0
        self.total_bytes = 0

    def timeout(self) -> float:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise SecurePathError("PostgreSQL bootstrap timed out")
        return min(IO_TIMEOUT_SECONDS, remaining)

    def consume_frame(self, frame_size: int) -> None:
        self.message_count += 1
        self.total_bytes += frame_size
        if self.message_count > MAX_MESSAGES or self.total_bytes > MAX_TOTAL_BYTES:
            raise SecurePathError("PostgreSQL bootstrap protocol budget exceeded")


def _read_exact(connection: socket.socket, size: int, budget: ProtocolBudget) -> bytes:
    if size < 0 or size > MAX_FRAME_BYTES:
        raise SecurePathError("PostgreSQL bootstrap frame size is invalid")
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        try:
            connection.settimeout(budget.timeout())
            chunk = connection.recv(remaining)
        except TimeoutError as error:
            raise SecurePathError("PostgreSQL bootstrap timed out") from error
        except OSError as error:
            raise SecurePathError("PostgreSQL bootstrap protocol I/O failed") from error
        if not chunk:
            raise SecurePathError("PostgreSQL bootstrap protocol frame is truncated")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_message(
    connection: socket.socket,
    budget: Optional[ProtocolBudget] = None,  # noqa: UP045 - system Python 3.9
) -> tuple[bytes, bytes]:
    active_budget = budget or ProtocolBudget()
    message_type = _read_exact(connection, 1, active_budget)
    length_bytes = _read_exact(connection, 4, active_budget)
    message_length = struct.unpack("!I", length_bytes)[0]
    if message_length < 4 or message_length > MAX_FRAME_BYTES:
        raise SecurePathError("PostgreSQL bootstrap frame length is invalid")
    active_budget.consume_frame(message_length + 1)
    return message_type, _read_exact(connection, message_length - 4, active_budget)


def _validate_error_fields(payload: bytes) -> None:
    if not payload or payload[-1:] != b"\0":
        raise SecurePathError("PostgreSQL bootstrap protocol ErrorResponse is invalid")
    offset = 0
    while offset < len(payload) - 1:
        field_code = payload[offset : offset + 1]
        if not field_code or field_code == b"\0":
            raise SecurePathError("PostgreSQL bootstrap protocol ErrorResponse is invalid")
        terminator = payload.find(b"\0", offset + 1)
        if terminator == -1:
            raise SecurePathError("PostgreSQL bootstrap protocol ErrorResponse is invalid")
        try:
            payload[offset + 1 : terminator].decode("utf-8")
        except UnicodeDecodeError as error:
            raise SecurePathError(
                "PostgreSQL bootstrap protocol ErrorResponse encoding is invalid"
            ) from error
        offset = terminator + 1


def _database_error(payload: bytes) -> SecurePathError:
    _validate_error_fields(payload)
    return SecurePathError("PostgreSQL bootstrap server rejected the operation")


def _validate_ready(payload: bytes) -> None:
    if len(payload) != 1 or payload not in {b"I", b"T", b"E"}:
        raise SecurePathError("PostgreSQL bootstrap protocol ReadyForQuery is invalid")


def _parse_data_row(payload: bytes) -> tuple[Optional[str], ...]:  # noqa: UP045
    if len(payload) < 2:
        raise SecurePathError("PostgreSQL bootstrap DataRow is truncated")
    column_count = struct.unpack("!H", payload[:2])[0]
    if column_count > MAX_COLUMNS:
        raise SecurePathError("PostgreSQL bootstrap DataRow has too many columns")
    offset = 2
    columns: list[Optional[str]] = []  # noqa: UP045
    for _ in range(column_count):
        if offset + 4 > len(payload):
            raise SecurePathError("PostgreSQL bootstrap DataRow is truncated")
        value_length = struct.unpack("!i", payload[offset : offset + 4])[0]
        offset += 4
        if value_length == -1:
            columns.append(None)
            continue
        if value_length < 0 or value_length > MAX_VALUE_BYTES:
            raise SecurePathError("PostgreSQL bootstrap DataRow value length is invalid")
        if offset + value_length > len(payload):
            raise SecurePathError("PostgreSQL bootstrap DataRow is truncated")
        try:
            columns.append(payload[offset : offset + value_length].decode("utf-8"))
        except UnicodeDecodeError as error:
            raise SecurePathError("PostgreSQL bootstrap DataRow encoding is invalid") from error
        offset += value_length
    if offset != len(payload):
        raise SecurePathError("PostgreSQL bootstrap DataRow has trailing bytes")
    return tuple(columns)


def _validate_row_description(payload: bytes) -> None:
    if len(payload) < 2:
        raise SecurePathError("PostgreSQL bootstrap RowDescription is truncated")
    field_count = struct.unpack("!H", payload[:2])[0]
    if field_count > MAX_COLUMNS:
        raise SecurePathError("PostgreSQL bootstrap RowDescription has too many fields")
    offset = 2
    for _ in range(field_count):
        terminator = payload.find(b"\0", offset)
        if terminator == -1 or terminator - offset > MAX_VALUE_BYTES:
            raise SecurePathError("PostgreSQL bootstrap RowDescription is invalid")
        try:
            payload[offset:terminator].decode("utf-8")
        except UnicodeDecodeError as error:
            raise SecurePathError(
                "PostgreSQL bootstrap RowDescription encoding is invalid"
            ) from error
        offset = terminator + 1
        if offset + 18 > len(payload):
            raise SecurePathError("PostgreSQL bootstrap RowDescription is truncated")
        offset += 18
    if offset != len(payload):
        raise SecurePathError("PostgreSQL bootstrap RowDescription has trailing bytes")


def _query(
    connection: socket.socket,
    query: str,
    budget: Optional[ProtocolBudget] = None,  # noqa: UP045 - system Python 3.9
) -> list[tuple[Optional[str], ...]]:  # noqa: UP045 - macOS system Python 3.9
    active_budget = budget or ProtocolBudget()
    query_payload = query.encode("utf-8") + b"\0"
    if len(query_payload) > MAX_VALUE_BYTES:
        raise SecurePathError("PostgreSQL bootstrap query is too large")
    try:
        connection.settimeout(active_budget.timeout())
        connection.sendall(b"Q" + struct.pack("!I", len(query_payload) + 4) + query_payload)
    except TimeoutError as error:
        raise SecurePathError("PostgreSQL bootstrap timed out") from error
    except OSError as error:
        raise SecurePathError("PostgreSQL bootstrap protocol I/O failed") from error
    rows: list[tuple[Optional[str], ...]] = []  # noqa: UP045
    command_complete = False
    while True:
        message_type, payload = _read_message(connection, active_budget)
        if message_type == b"D":
            if len(rows) >= MAX_ROWS:
                raise SecurePathError("PostgreSQL bootstrap returned too many rows")
            rows.append(_parse_data_row(payload))
        elif message_type == b"T":
            _validate_row_description(payload)
        elif message_type == b"C":
            if not payload or payload[-1:] != b"\0":
                raise SecurePathError("PostgreSQL bootstrap CommandComplete is invalid")
            try:
                payload[:-1].decode("utf-8")
            except UnicodeDecodeError as error:
                raise SecurePathError(
                    "PostgreSQL bootstrap CommandComplete encoding is invalid"
                ) from error
            command_complete = True
        elif message_type == b"I":
            if payload:
                raise SecurePathError("PostgreSQL bootstrap EmptyQueryResponse is invalid")
            command_complete = True
        elif message_type == b"N":
            _validate_error_fields(payload)
        elif message_type == b"E":
            raise _database_error(payload)
        elif message_type == b"Z":
            _validate_ready(payload)
            if not command_complete:
                raise SecurePathError(
                    "PostgreSQL bootstrap ReadyForQuery arrived before command completion"
                )
            return rows
        else:
            raise SecurePathError("PostgreSQL bootstrap protocol message is unexpected")


def _validate_parameter_status(payload: bytes) -> None:
    if not payload or payload[-1:] != b"\0":
        raise SecurePathError("PostgreSQL bootstrap ParameterStatus is invalid")
    parts = payload[:-1].split(b"\0")
    if len(parts) != 2 or not parts[0]:
        raise SecurePathError("PostgreSQL bootstrap ParameterStatus is invalid")
    try:
        parts[0].decode("utf-8")
        parts[1].decode("utf-8")
    except UnicodeDecodeError as error:
        raise SecurePathError("PostgreSQL bootstrap ParameterStatus encoding is invalid") from error


def _perform_bootstrap(connection: socket.socket, user: str, database: str) -> None:
    budget = ProtocolBudget()
    parameters = (
        b"user\0" + user.encode("ascii") + b"\0database\0postgres\0client_encoding\0UTF8\0\0"
    )
    startup = struct.pack("!I", 196608) + parameters
    try:
        connection.settimeout(budget.timeout())
        connection.sendall(struct.pack("!I", len(startup) + 4) + startup)
    except TimeoutError as error:
        raise SecurePathError("PostgreSQL bootstrap timed out") from error
    except OSError as error:
        raise SecurePathError("PostgreSQL bootstrap protocol I/O failed") from error
    authenticated = False
    while True:
        message_type, payload = _read_message(connection, budget)
        if message_type == b"R":
            if len(payload) != 4:
                raise SecurePathError("PostgreSQL bootstrap Authentication message is invalid")
            authentication_code = struct.unpack("!I", payload)[0]
            if authentication_code != 0:
                raise SecurePathError("PostgreSQL bootstrap requires local trust authentication")
            if authenticated:
                raise SecurePathError("PostgreSQL bootstrap authentication was duplicated")
            authenticated = True
        elif message_type == b"S":
            _validate_parameter_status(payload)
        elif message_type == b"K":
            if len(payload) != 8:
                raise SecurePathError("PostgreSQL bootstrap BackendKeyData is invalid")
        elif message_type == b"N":
            _validate_error_fields(payload)
        elif message_type == b"E":
            raise _database_error(payload)
        elif message_type == b"Z":
            _validate_ready(payload)
            if not authenticated:
                raise SecurePathError(
                    "PostgreSQL bootstrap ReadyForQuery arrived before authentication"
                )
            break
        else:
            raise SecurePathError("PostgreSQL bootstrap startup message is unexpected")
    rows = _query(
        connection,
        f"SELECT 1 FROM pg_database WHERE datname = '{database}'",
        budget,
    )
    if not rows:
        _query(connection, f'CREATE DATABASE "{database}"', budget)
    try:
        connection.settimeout(budget.timeout())
        connection.sendall(b"X" + struct.pack("!I", 4))
    except TimeoutError as error:
        raise SecurePathError("PostgreSQL bootstrap timed out") from error
    except OSError as error:
        raise SecurePathError("PostgreSQL bootstrap protocol I/O failed") from error


def bootstrap_database(user: str, database: str) -> None:
    if not DATABASE_IDENTIFIER.fullmatch(user) or not DATABASE_IDENTIFIER.fullmatch(database):
        raise SecurePathError("PostgreSQL bootstrap identifiers are invalid")
    bound_fd_text = os.environ.get("RSI_ATLAS_BOUND_POSTGRES_FD", "")
    if not bound_fd_text.isdigit():
        raise SecurePathError("PostgreSQL bootstrap requires a bound directory descriptor")
    try:
        bound_fd = int(bound_fd_text)
        bound_stat = os.fstat(bound_fd)
        os.set_inheritable(bound_fd, False)
        cwd_stat = os.stat(".", follow_symlinks=False)
        if (bound_stat.st_dev, bound_stat.st_ino) != (cwd_stat.st_dev, cwd_stat.st_ino):
            raise SecurePathError("PostgreSQL bootstrap directory identity changed")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(IO_TIMEOUT_SECONDS)
            connection.connect("socket/.s.PGSQL.5432")
            _perform_bootstrap(connection, user, database)
    except SecurePathError:
        raise
    except (OSError, UnicodeError, struct.error, ValueError):
        raise SecurePathError("PostgreSQL bootstrap protocol failure") from None


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
