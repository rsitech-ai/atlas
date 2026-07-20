"""Phase 6 loopback API contract tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from rsi_atlas_engine.api import create_app
from rsi_atlas_engine.phase6 import Phase6Service
from rsi_atlas_recovery import SafeModeController
from rsi_atlas_security.ipc import ensure_ipc_token


def _unused_status():
    raise RuntimeError("unused")


def test_phase6_evaluation_codex_backup_safe_mode_release(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RSI_ATLAS_DATA_ROOT", str(tmp_path / "runtime"))
    client = TestClient(create_app(phase6_service=Phase6Service()))

    evaluation = client.post("/v1/evaluation:run", json={"include_judge": True})
    assert evaluation.status_code == 200
    body = evaluation.json()
    assert body["dataset_id"] == "dataset:retrieval_regression"
    assert body["run"]["status"] == "blocked"
    assert body["promotion"]["outcome"] in {"require_human_review", "reject"}

    gate = client.post(
        "/v1/engineering/codex:gate",
        json={
            "failure_summary": "schema fail",
            "raw_inputs": {"api_key": "secret", "query": "ok"},
            "expected_behavior": "pass",
            "actual_behavior": "fail",
            "diff_text": "--- a\n+++ b\n+return True\n",
        },
    )
    assert gate.status_code == 200
    gate_body = gate.json()
    assert gate_body["bundle"]["sanitized_inputs"]["api_key"] == "[REDACTED]"
    assert gate_body["patch"]["auto_applied"] is False
    assert gate_body["authority_denials"][0]["denied"] is True

    source = tmp_path / "ws"
    source.mkdir()
    (source / "f.txt").write_text("x", encoding="utf-8")
    backup_root = tmp_path / "backup"
    created = client.post(
        "/v1/recovery/backup:create",
        json={"source_root": str(source), "destination_root": str(backup_root)},
    )
    assert created.status_code == 200
    assert created.json()["kind"] == "workspace"

    verified = client.post(
        "/v1/recovery/backup:restore-verify",
        json={"backup_root": str(backup_root)},
    )
    assert verified.status_code == 200
    assert verified.json()["verified"] is True

    entered = client.post("/v1/recovery/safe-mode:enter", json={"reason": "test"})
    assert entered.status_code == 200
    assert entered.json()["active"] is True
    current = client.get("/v1/recovery/safe-mode")
    assert current.status_code == 200
    assert current.json()["active"] is True

    release = client.post("/v1/release:check", json={"require_release": True})
    assert release.status_code == 200
    report = release.json()
    assert report["release_ready"] is False
    assert "notarization_blocked" in report["blockers"]
    assert report["signing_status"] == "unsigned_development"


def test_default_app_caches_safe_mode_and_reloads_it_after_recreation(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RSI_ATLAS_DATA_ROOT", str(tmp_path / "runtime"))
    first = TestClient(create_app(status_factory=_unused_status))

    entered = first.post("/v1/recovery/safe-mode:enter", json={"reason": "operator"})
    assert entered.status_code == 200
    assert first.get("/v1/recovery/safe-mode").json()["active"] is True

    recreated = TestClient(create_app(status_factory=_unused_status))
    current = recreated.get("/v1/recovery/safe-mode")
    assert current.status_code == 200
    assert current.json()["active"] is True


def test_authenticated_safe_mode_exit_clears_persisted_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("RSI_ATLAS_DATA_ROOT", str(tmp_path / "runtime"))
    token_path = tmp_path / "engine.token"
    token = ensure_ipc_token(token_path)
    first = TestClient(
        create_app(
            status_factory=_unused_status,
            require_ipc_auth=True,
            ipc_token_path=token_path,
        )
    )
    auth = {"Authorization": f"Bearer {token}"}
    assert (
        first.post(
            "/v1/recovery/safe-mode:enter",
            headers=auth,
            json={"reason": "operator"},
        ).status_code
        == 200
    )

    unauthenticated = first.post("/v1/recovery/safe-mode:exit")
    assert unauthenticated.status_code == 401
    exited = first.post("/v1/recovery/safe-mode:exit", headers=auth)
    assert exited.status_code == 200
    assert exited.json()["active"] is False

    recreated = TestClient(
        create_app(
            status_factory=_unused_status,
            require_ipc_auth=True,
            ipc_token_path=token_path,
        )
    )
    assert recreated.get("/v1/recovery/safe-mode", headers=auth).json()["active"] is False


def test_safe_mode_exit_requires_owner_token_when_global_auth_is_disabled(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "runtime"
    monkeypatch.setenv("RSI_ATLAS_DATA_ROOT", str(data_root))
    data_root.mkdir(mode=0o700)
    token = ensure_ipc_token(data_root / "ipc" / "engine.token")
    client = TestClient(create_app(status_factory=_unused_status, require_ipc_auth=False))
    assert (
        client.post("/v1/recovery/safe-mode:enter", json={"reason": "operator"}).status_code == 200
    )

    assert client.post("/v1/recovery/safe-mode:exit").status_code == 401
    exited = client.post(
        "/v1/recovery/safe-mode:exit",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert exited.status_code == 200
    assert exited.json()["active"] is False


def test_safe_mode_exit_fails_closed_when_persistence_does_not_clear_state(
    tmp_path: Path, monkeypatch
) -> None:
    data_root = tmp_path / "runtime"
    monkeypatch.setenv("RSI_ATLAS_DATA_ROOT", str(data_root))
    data_root.mkdir(mode=0o700)
    token = ensure_ipc_token(data_root / "ipc" / "engine.token")
    client = TestClient(create_app(status_factory=_unused_status, require_ipc_auth=False))
    assert (
        client.post("/v1/recovery/safe-mode:enter", json={"reason": "operator"}).status_code == 200
    )

    monkeypatch.setattr(SafeModeController, "exit", lambda self: self.state)
    response = client.post(
        "/v1/recovery/safe-mode:exit",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 503
    assert response.json() == {"detail": "Safe Mode is unavailable."}
