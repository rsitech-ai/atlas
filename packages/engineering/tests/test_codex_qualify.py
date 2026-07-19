"""Codex qualification gate tests."""

from __future__ import annotations

from pathlib import Path

from rsi_atlas_engineering.codex_qualify import qualify_codex_app_server


def test_qualify_fail_closed_without_binary(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("RSI_ATLAS_CODEX_BIN", raising=False)
    monkeypatch.setattr("rsi_atlas_engineering.codex_qualify.shutil.which", lambda _name: None)
    result = qualify_codex_app_server()
    assert result.available is False
    assert "codex_binary_missing" in result.blockers


def test_qualify_rejects_network_flag(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("RSI_ATLAS_CODEX_ALLOW_NETWORK", "1")
    fake = tmp_path / "codex"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("RSI_ATLAS_CODEX_BIN", str(fake))
    monkeypatch.setattr("rsi_atlas_engineering.codex_qualify.shutil.which", lambda _name: None)
    result = qualify_codex_app_server(worktree_hint=tmp_path)
    assert result.available is False
    assert "deny_network_violated" in result.blockers
