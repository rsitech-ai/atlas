"""Authenticated IPC readiness-helper tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

from rsi_atlas_security.ipc import IpcTransportMode

ROOT = Path(__file__).resolve().parents[1]


def _load_wait_module():
    path = ROOT / "script" / "wait_engine_ipc.py"
    spec = importlib.util.spec_from_file_location("rsi_atlas_wait_engine_ipc", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_require_auth_waits_for_token_creation(monkeypatch, tmp_path: Path) -> None:
    module = _load_wait_module()
    token_reads = iter((None, "created-after-launch"))
    clock_reads = iter((0.0, 0.1, 0.2))
    requests: list[dict[str, str]] = []
    cfg = SimpleNamespace(
        mode=IpcTransportMode.UNIX_DOMAIN,
        token_path=tmp_path / "engine.token",
        uds_path=tmp_path / "engine.sock",
    )
    monkeypatch.setattr(
        module.RuntimePaths,
        "from_environment",
        lambda: SimpleNamespace(data_root=tmp_path),
    )
    monkeypatch.setattr(module, "resolve_ipc_bind", lambda *, data_root: cfg)
    monkeypatch.setattr(module, "load_ipc_token", lambda path: next(token_reads))
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock_reads))
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)

    def fake_get(**kwargs):
        requests.append(kwargs["headers"])
        return 200, b"{}"

    monkeypatch.setattr(module, "_http_get", fake_get)

    assert module.main(["--timeout-seconds", "1", "--require-auth"]) == 0
    assert requests == [{"Authorization": "Bearer created-after-launch"}]
