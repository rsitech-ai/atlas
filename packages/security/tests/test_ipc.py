"""IPC transport policy tests."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from rsi_atlas_security.ipc import (
    IpcTransportError,
    IpcTransportMode,
    assert_no_unintended_tcp,
    ensure_ipc_token,
    resolve_ipc_bind,
    tokens_match,
)


def test_release_mode_forces_uds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RSI_ATLAS_RELEASE_IPC", "1")
    monkeypatch.delenv("RSI_ATLAS_ALLOW_LOOPBACK_TCP", raising=False)
    cfg = resolve_ipc_bind(data_root=tmp_path)
    assert cfg.mode is IpcTransportMode.UNIX_DOMAIN
    assert cfg.uds_path == tmp_path / "ipc" / "engine.sock"
    assert_no_unintended_tcp(release_mode=True, mode=cfg.mode)


def test_release_rejects_tcp_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RSI_ATLAS_RELEASE_IPC", "1")
    monkeypatch.setenv("RSI_ATLAS_ALLOW_LOOPBACK_TCP", "1")
    with pytest.raises(IpcTransportError, match="forbids loopback TCP"):
        resolve_ipc_bind(data_root=tmp_path)


def test_explicit_loopback_tcp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RSI_ATLAS_RELEASE_IPC", raising=False)
    monkeypatch.setenv("RSI_ATLAS_ALLOW_LOOPBACK_TCP", "1")
    monkeypatch.setenv("RSI_ATLAS_ENGINE_PORT", "8765")
    cfg = resolve_ipc_bind(data_root=tmp_path)
    assert cfg.mode is IpcTransportMode.LOOPBACK_TCP
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8765


def test_default_without_tcp_flag_is_uds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RSI_ATLAS_RELEASE_IPC", raising=False)
    monkeypatch.delenv("RSI_ATLAS_ALLOW_LOOPBACK_TCP", raising=False)
    cfg = resolve_ipc_bind(data_root=tmp_path)
    assert cfg.mode is IpcTransportMode.UNIX_DOMAIN


def test_token_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "ipc" / "engine.token"
    token = ensure_ipc_token(path)
    assert len(token) >= 32
    assert path.stat().st_mode & 0o777 == 0o600
    again = ensure_ipc_token(path)
    assert again == token
    assert tokens_match(provided=token, expected=token)
    assert not tokens_match(provided="wrong", expected=token)


def test_non_loopback_host_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RSI_ATLAS_ALLOW_LOOPBACK_TCP", "1")
    monkeypatch.setenv("RSI_ATLAS_ENGINE_HOST", "0.0.0.0")
    with pytest.raises(IpcTransportError, match="loopback"):
        resolve_ipc_bind(data_root=tmp_path)


def test_assert_tcp_in_release() -> None:
    with pytest.raises(IpcTransportError, match="114"):
        assert_no_unintended_tcp(release_mode=True, mode=IpcTransportMode.LOOPBACK_TCP)


def test_env_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep test process env tidy for parallel suites.
    for key in (
        "RSI_ATLAS_RELEASE_IPC",
        "RSI_ATLAS_ALLOW_LOOPBACK_TCP",
        "RSI_ATLAS_ENGINE_HOST",
        "RSI_ATLAS_ENGINE_PORT",
    ):
        monkeypatch.delenv(key, raising=False)
    assert "RSI_ATLAS_RELEASE_IPC" not in os.environ
