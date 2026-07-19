"""Phase 6 loopback API contract tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from rsi_atlas_engine.api import create_app
from rsi_atlas_engine.phase6 import Phase6Service


def test_phase6_evaluation_codex_backup_safe_mode_release(tmp_path: Path) -> None:
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
