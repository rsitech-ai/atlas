from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from rsi_atlas_document_worker.preflight import run_preflight
from rsi_atlas_document_worker.protocol import (
    DocumentWorkerRequest,
    WorkerOperation,
    WorkerResponseStatus,
)
from rsi_atlas_ingestion.worker_runner import DocumentWorkerRunner


def test_preflight_accepts_born_digital_fixture() -> None:
    fixture = Path("packages/ingestion/benchmarks/pdf/fixtures/crypto_technical_three_page.pdf")
    fd = os.open(fixture, os.O_RDONLY)
    try:
        evidence = run_preflight(artifact_fd=fd)
    finally:
        os.close(fd)
    assert evidence["page_count"] == 3
    assert evidence["encryption_password_state"] == "pass"
    assert evidence["malformed_structure"] == "pass"
    assert len(evidence["pages"]) == 3


def test_preflight_routes_encrypted_fixture() -> None:
    fixture = Path("packages/ingestion/benchmarks/pdf/fixtures/encrypted_password.pdf")
    fd = os.open(fixture, os.O_RDONLY)
    try:
        evidence = run_preflight(artifact_fd=fd)
    finally:
        os.close(fd)
    assert evidence["encryption_password_state"] == "fail"
    assert "password_required_or_encrypted" in evidence["warnings"]


def test_sandboxed_preflight_writes_evidence(tmp_path: Path) -> None:
    fixture = Path("packages/ingestion/benchmarks/pdf/fixtures/audit_mixed_font.pdf")
    payload = fixture.read_bytes()
    request = DocumentWorkerRequest(
        operation=WorkerOperation.PREFLIGHT,
        run_id="preflight-live-001",
        artifact_sha256=hashlib.sha256(payload).hexdigest(),
        artifact_size_bytes=len(payload),
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    result = DocumentWorkerRunner(timeout_seconds=30).run_request(
        request=request,
        artifact_path=fixture,
        run_directory=run_dir,
    )
    assert result.response.status is WorkerResponseStatus.SUCCEEDED
    evidence = json.loads((run_dir / "preflight.json").read_text(encoding="utf-8"))
    assert evidence["page_count"] == 1
