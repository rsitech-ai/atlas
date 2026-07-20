"""Durable, fail-closed Safe Mode capability state."""

from __future__ import annotations

import errno
import os
import secrets
import stat
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from rsi_atlas_contracts import SAFE_MODE_DISABLED_CAPABILITIES, SafeModeCapability, SafeModeState

_STATE_MODE = 0o600
_MAX_STATE_BYTES = 16 * 1024
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_WRITE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


class SafeModeBlocked(RuntimeError):
    """Raised when Safe Mode disables a requested capability."""

    def __init__(self, capability: SafeModeCapability) -> None:
        self.capability = capability
        super().__init__(f"Safe Mode blocks capability: {capability.value}")


class SafeModeStore:
    """Persist Safe Mode at a fixed, owner-private location below ``data_root``."""

    def __init__(self, data_root: Path) -> None:
        self.path = Path(data_root) / "recovery" / "safe-mode.json"

    def load(self) -> SafeModeState:
        """Load trusted state, failing closed for every unsafe or invalid condition."""
        try:
            directory_fd = self._open_directory()
        except FileNotFoundError:
            return _inactive_state()
        except OSError:
            return _unreadable_state()

        try:
            try:
                file_fd = os.open(self.path.name, _READ_FLAGS, dir_fd=directory_fd)
            except FileNotFoundError:
                return _inactive_state()
            try:
                metadata = os.fstat(file_fd)
                if not _trusted_file(metadata):
                    return _unreadable_state()
                payload = _read_limited(file_fd)
            finally:
                os.close(file_fd)
            return SafeModeState.model_validate_json(payload)
        except (OSError, ValueError):
            return _unreadable_state()
        finally:
            os.close(directory_fd)

    def enter(self, *, reason: str, entered_at: datetime) -> SafeModeState:
        state = SafeModeState(
            active=True,
            disabled_capabilities=SAFE_MODE_DISABLED_CAPABILITIES,
            entered_at=entered_at,
            reason=reason,
        )
        self.save(state)
        return state

    def exit(self) -> SafeModeState:
        state = _inactive_state()
        self.save(state)
        return state

    def save(self, state: SafeModeState) -> None:
        """Atomically replace the state file after fully syncing a private temp file."""
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory_fd = self._open_directory()
        temporary_name = f".safe-mode-{secrets.token_hex(16)}.tmp"
        temporary_fd: int | None = None
        replaced = False
        try:
            temporary_fd = os.open(temporary_name, _WRITE_FLAGS, _STATE_MODE, dir_fd=directory_fd)
            payload = state.model_dump_json().encode("utf-8")
            _write_all(temporary_fd, payload)
            os.fchmod(temporary_fd, _STATE_MODE)
            os.fsync(temporary_fd)
            os.close(temporary_fd)
            temporary_fd = None
            os.replace(
                temporary_name,
                self.path.name,
                src_dir_fd=directory_fd,
                dst_dir_fd=directory_fd,
            )
            replaced = True
            os.fsync(directory_fd)
        finally:
            if temporary_fd is not None:
                os.close(temporary_fd)
            if not replaced:
                with suppress(FileNotFoundError):
                    os.unlink(temporary_name, dir_fd=directory_fd)
            os.close(directory_fd)

    def _open_directory(self) -> int:
        return os.open(self.path.parent, _DIRECTORY_FLAGS)


class SafeModeController:
    def __init__(self, store: SafeModeStore | None = None) -> None:
        self._store = store
        self._state = store.load() if store is not None else _inactive_state()

    @property
    def state(self) -> SafeModeState:
        return self._state

    def enter(self, *, reason: str, entered_at: datetime) -> SafeModeState:
        state = SafeModeState(
            active=True,
            disabled_capabilities=SAFE_MODE_DISABLED_CAPABILITIES,
            entered_at=entered_at,
            reason=reason,
        )
        self._set_state(state)
        return state

    def exit(self) -> SafeModeState:
        state = _inactive_state()
        self._set_state(state)
        return state

    def is_disabled(self, capability: SafeModeCapability) -> bool:
        return self._state.active and capability in self._state.disabled_capabilities

    def require(self, capability: SafeModeCapability) -> None:
        if self.is_disabled(capability):
            raise SafeModeBlocked(capability)

    def _set_state(self, state: SafeModeState) -> None:
        if self._store is not None:
            self._store.save(state)
        self._state = state


def _inactive_state() -> SafeModeState:
    return SafeModeState(active=False, disabled_capabilities=frozenset())


def _unreadable_state() -> SafeModeState:
    return SafeModeState(
        active=True,
        disabled_capabilities=SAFE_MODE_DISABLED_CAPABILITIES,
        entered_at=datetime.now(UTC),
        reason="safe_mode_state_unreadable",
    )


def _trusted_file(metadata: os.stat_result) -> bool:
    return (
        stat.S_ISREG(metadata.st_mode)
        and stat.S_IMODE(metadata.st_mode) == _STATE_MODE
        and metadata.st_uid == os.getuid()
    )


def _read_limited(file_fd: int) -> bytes:
    payload = bytearray()
    while len(payload) <= _MAX_STATE_BYTES:
        chunk = os.read(file_fd, min(4096, _MAX_STATE_BYTES + 1 - len(payload)))
        if not chunk:
            return bytes(payload)
        payload.extend(chunk)
    raise ValueError("Safe Mode state exceeds the bounded size")


def _write_all(file_fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(file_fd, view)
        if written == 0:
            raise OSError(errno.EIO, "could not write Safe Mode state")
        view = view[written:]
