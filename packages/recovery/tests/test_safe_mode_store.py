"""Durable, fail-closed Safe Mode state tests."""

from __future__ import annotations

import errno
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from types import SimpleNamespace

import pytest
from rsi_atlas_contracts import SAFE_MODE_DISABLED_CAPABILITIES, SafeModeCapability
from rsi_atlas_recovery import safe_mode

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def _store(data_root: Path):
    return safe_mode.SafeModeStore(data_root)


def _assert_fail_closed(state) -> None:
    assert state.active is True
    assert state.disabled_capabilities == SAFE_MODE_DISABLED_CAPABILITIES
    assert state.reason == "safe_mode_state_unreadable"


def test_missing_state_is_inactive_at_the_fixed_recovery_path(tmp_path: Path) -> None:
    store = _store(tmp_path / "data")

    assert store.path == tmp_path / "data" / "recovery" / "safe-mode.json"
    assert store.load().active is False


def test_enter_persists_active_state_across_recreation(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    store = _store(data_root)

    state = store.enter(reason="integrity_failure", entered_at=NOW)

    assert state.active is True
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600
    recreated = _store(data_root).load()
    assert recreated == state


def test_exit_persists_inactive_state_across_recreation(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    store = _store(data_root)
    store.enter(reason="integrity_failure", entered_at=NOW)

    state = store.exit()

    assert state.active is False
    assert _store(data_root).load() == state


def test_malformed_state_fails_closed(tmp_path: Path) -> None:
    store = _store(tmp_path / "data")
    store.path.parent.mkdir(parents=True)
    store.path.write_text("not-json", encoding="utf-8")
    store.path.chmod(0o600)

    _assert_fail_closed(store.load())


def test_symlinked_state_fails_closed(tmp_path: Path) -> None:
    store = _store(tmp_path / "data")
    store.path.parent.mkdir(parents=True)
    target = tmp_path / "state.json"
    target.write_text('{"active": false, "disabled_capabilities": []}', encoding="utf-8")
    store.path.symlink_to(target)

    _assert_fail_closed(store.load())


def test_overly_permissive_state_fails_closed(tmp_path: Path) -> None:
    store = _store(tmp_path / "data")
    store.enter(reason="integrity_failure", entered_at=NOW)
    store.path.chmod(0o644)

    _assert_fail_closed(store.load())


def test_wrong_owner_state_metadata_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path / "data")
    store.enter(reason="integrity_failure", entered_at=NOW)
    actual_fstat = safe_mode.os.fstat

    def wrong_owner(fd: int):
        metadata = actual_fstat(fd)
        if stat.S_ISREG(metadata.st_mode):
            return SimpleNamespace(st_mode=metadata.st_mode, st_uid=metadata.st_uid + 1)
        return metadata

    monkeypatch.setattr(safe_mode.os, "fstat", wrong_owner)

    _assert_fail_closed(store.load())


def test_controller_recreates_store_state_and_blocks_disabled_capability(tmp_path: Path) -> None:
    store = _store(tmp_path / "data")
    controller = safe_mode.SafeModeController(store)
    assert controller.require(SafeModeCapability.COLLECTORS) is None
    controller.enter(reason="integrity_failure", entered_at=NOW)

    recreated = safe_mode.SafeModeController(_store(tmp_path / "data"))

    assert recreated.state.active is True
    with pytest.raises(safe_mode.SafeModeBlocked, match="models"):
        recreated.require(SafeModeCapability.MODELS)


def test_existing_controller_refreshes_store_at_guard_boundaries(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    controller = safe_mode.SafeModeController(_store(data_root))
    external_store = _store(data_root)

    external_store.enter(reason="integrity_failure", entered_at=NOW)

    assert controller.is_disabled(SafeModeCapability.MODELS) is True
    with pytest.raises(safe_mode.SafeModeBlocked, match="models"):
        controller.require(SafeModeCapability.MODELS)
    assert controller.state.active is True


def test_fifo_state_fails_closed_without_blocking_load(tmp_path: Path) -> None:
    store = _store(tmp_path / "data")
    store.path.parent.mkdir(parents=True)
    os.mkfifo(store.path, 0o600)
    results: Queue[object] = Queue()
    worker = Thread(target=lambda: results.put(store.load()), daemon=True)
    worker.start()
    worker.join(timeout=0.2)
    blocked = worker.is_alive()

    if blocked:
        writer_fd = os.open(store.path, os.O_WRONLY | os.O_NONBLOCK)
        os.close(writer_fd)
        worker.join(timeout=1)

    assert blocked is False
    try:
        state = results.get_nowait()
    except Empty as error:
        raise AssertionError("Safe Mode FIFO load did not return a state") from error
    _assert_fail_closed(state)


def test_failed_exit_directory_sync_restores_fail_closed_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path / "data")
    controller = safe_mode.SafeModeController(store)
    controller.enter(reason="integrity_failure", entered_at=NOW)
    actual_fsync = safe_mode.os.fsync
    directory_sync_failed = False

    def fail_first_directory_sync(fd: int) -> None:
        nonlocal directory_sync_failed
        if stat.S_ISDIR(safe_mode.os.fstat(fd).st_mode) and not directory_sync_failed:
            directory_sync_failed = True
            raise OSError("directory sync failed after replacement")
        actual_fsync(fd)

    monkeypatch.setattr(safe_mode.os, "fsync", fail_first_directory_sync)

    try:
        outcome = controller.exit()
    except OSError:
        outcome = None

    assert directory_sync_failed is True
    assert outcome is not None
    _assert_fail_closed(outcome)
    _assert_fail_closed(controller.state)
    _assert_fail_closed(store.load())


def test_exit_guard_blocks_after_sync_failure_and_recovery_enospc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path / "data")
    controller = safe_mode.SafeModeController(store)
    controller.enter(reason="integrity_failure", entered_at=NOW)
    actual_fsync = safe_mode.os.fsync
    actual_open = safe_mode.os.open
    actual_replace = safe_mode.os.replace
    inactive_state_replaced = False
    directory_sync_failed = False
    recovery_temp_open_attempted = False

    def record_inactive_replacement(source, destination, *args, **kwargs) -> None:
        nonlocal inactive_state_replaced
        actual_replace(source, destination, *args, **kwargs)
        if destination == store.path.name:
            inactive_state_replaced = True

    def fail_directory_sync_after_inactive_replacement(fd: int) -> None:
        nonlocal directory_sync_failed
        if (
            inactive_state_replaced
            and stat.S_ISDIR(safe_mode.os.fstat(fd).st_mode)
            and not directory_sync_failed
        ):
            directory_sync_failed = True
            raise OSError("directory sync failed after inactive replacement")
        actual_fsync(fd)

    def reject_recovery_temp_after_sync_failure(path, flags, mode=0o777, *, dir_fd=None) -> int:
        nonlocal recovery_temp_open_attempted
        if directory_sync_failed and str(path).startswith(".safe-mode-"):
            recovery_temp_open_attempted = True
            raise OSError(errno.ENOSPC, "no space for recovery temporary state")
        return actual_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(safe_mode.os, "replace", record_inactive_replacement)
    monkeypatch.setattr(safe_mode.os, "fsync", fail_directory_sync_after_inactive_replacement)
    monkeypatch.setattr(safe_mode.os, "open", reject_recovery_temp_after_sync_failure)

    outcome = controller.exit()

    assert inactive_state_replaced is True
    assert directory_sync_failed is True
    _assert_fail_closed(outcome)
    _assert_fail_closed(store.load())
    with pytest.raises(safe_mode.SafeModeBlocked, match="models"):
        controller.require(SafeModeCapability.MODELS)
    assert recovery_temp_open_attempted is False
