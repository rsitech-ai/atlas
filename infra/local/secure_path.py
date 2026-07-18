#!/usr/bin/python3
"""Create RSI Atlas PostgreSQL roots without following filesystem symlinks."""

import errno
import os
import stat
import sys
from pathlib import Path

PRIVATE_MODE = 0o700
DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


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
        }
        os.execvpe(command[0], command, environment)
    finally:
        os.close(postgres_fd)


def main() -> int:
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
