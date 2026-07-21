from __future__ import annotations

import os
from pathlib import Path

import pytest
from rsi_atlas_engine.server import serve_release


class FakePostgres:
    def __init__(self) -> None:
        self.events: list[str] = []

    def start(self) -> None:
        self.events.append("start")

    def stop(self) -> None:
        self.events.append("stop")


def _release_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    resources = tmp_path / "resources"
    resources.mkdir(mode=0o755)
    (resources / "migrations").mkdir()
    security = resources / "security"
    security.mkdir()
    (security / "document-worker.sb").write_text("(version 1)\n", encoding="utf-8")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    data = tmp_path / "data"
    data.mkdir(mode=0o700)
    monkeypatch.setenv("RSI_ATLAS_RESOURCE_ROOT", str(resources))
    monkeypatch.setenv("RSI_ATLAS_RUNTIME_ROOT", str(runtime))
    monkeypatch.setenv("RSI_ATLAS_DATA_ROOT", str(data))
    monkeypatch.setenv("RSI_ATLAS_ALLOW_LOOPBACK_TCP", "1")
    return runtime, data


def test_release_server_starts_database_then_authenticated_uds_and_stops(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime, data = _release_environment(tmp_path, monkeypatch)
    postgres = FakePostgres()
    observed: dict[str, object] = {}

    def factory(actual_runtime: Path, actual_data: Path) -> FakePostgres:
        assert actual_runtime == runtime
        assert actual_data == data
        return postgres

    def run_uvicorn(application: str, **kwargs: object) -> None:
        postgres.events.append("uvicorn")
        observed["application"] = application
        observed.update(kwargs)

    result = serve_release(postgres_factory=factory, uvicorn_runner=run_uvicorn)

    assert result == 0
    assert postgres.events == ["start", "uvicorn", "stop"]
    assert observed == {
        "application": "rsi_atlas_engine.api:app",
        "uds": str(data / "ipc" / "engine.sock"),
        "factory": False,
        "log_level": "info",
    }
    assert (data / "ipc" / "engine.token").stat().st_mode & 0o777 == 0o600
    assert os.environ["RSI_ATLAS_RELEASE_IPC"] == "1"
    assert os.environ["RSI_ATLAS_IPC_AUTH"] == "1"
    assert "RSI_ATLAS_ALLOW_LOOPBACK_TCP" not in os.environ


def test_release_server_stops_database_when_server_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _release_environment(tmp_path, monkeypatch)
    postgres = FakePostgres()

    def fail_uvicorn(_application: str, **_kwargs: object) -> None:
        raise RuntimeError("server failed")

    with pytest.raises(RuntimeError, match="server failed"):
        serve_release(
            postgres_factory=lambda _runtime, _data: postgres,
            uvicorn_runner=fail_uvicorn,
        )

    assert postgres.events == ["start", "stop"]


def test_release_server_rejects_missing_embedded_runtime_before_database_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _release_environment(tmp_path, monkeypatch)
    monkeypatch.delenv("RSI_ATLAS_RUNTIME_ROOT")
    postgres = FakePostgres()

    with pytest.raises(ValueError, match="not configured"):
        serve_release(postgres_factory=lambda _runtime, _data: postgres)

    assert postgres.events == []
