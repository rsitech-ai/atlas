"""Durable, fail-closed Safe Mode state tests."""

from __future__ import annotations

import stat
from datetime import UTC, datetime
from pathlib import Path
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
