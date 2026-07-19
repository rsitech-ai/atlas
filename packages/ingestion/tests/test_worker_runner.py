from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from rsi_atlas_document_worker.protocol import WorkerResponseStatus
from rsi_atlas_ingestion.worker_runner import (
    DocumentWorkerRunner,
    DocumentWorkerRunnerError,
)


def _write_artifact(path: Path, payload: bytes) -> Path:
    path.write_bytes(payload)
    os.chmod(path, 0o600)
    return path


def test_runner_echo_hash_succeeds_under_seatbelt(tmp_path: Path) -> None:
    artifact = _write_artifact(tmp_path / "artifact.bin", b"rsi-atlas-echo")
    run_dir = tmp_path / "run-a"
    result = DocumentWorkerRunner(timeout_seconds=20).run_echo_hash(
        artifact_path=artifact,
        run_directory=run_dir,
        run_id="run-echo-live-001",
    )
    assert result.response.status is WorkerResponseStatus.SUCCEEDED
    assert result.response.artifact_sha256 == hashlib.sha256(b"rsi-atlas-echo").hexdigest()
    assert (run_dir / "echo_hash.json").is_file()
    assert not (run_dir / "echo_hash.json").is_symlink()


def test_runner_rejects_missing_sandbox_binary(tmp_path: Path) -> None:
    artifact = _write_artifact(tmp_path / "artifact.bin", b"x")
    runner = DocumentWorkerRunner(sandbox_executable=tmp_path / "missing-sandbox-exec")
    with pytest.raises(DocumentWorkerRunnerError) as raised:
        runner.run_echo_hash(
            artifact_path=artifact,
            run_directory=tmp_path / "run-missing",
            run_id="run-echo-live-002",
        )
    assert raised.value.code == "sandbox_unavailable"


def test_runner_kills_process_group_and_cleans_partial_outputs(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-timeout"
    run_dir.mkdir()
    (run_dir / "partial.out").write_bytes(b"partial")

    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    DocumentWorkerRunner._kill_process_group(process)
    assert process.poll() is not None
    DocumentWorkerRunner._cleanup_partial_outputs(run_dir)
    assert not (run_dir / "partial.out").exists()


def test_concurrent_runs_isolate_directories(tmp_path: Path) -> None:
    artifact = _write_artifact(tmp_path / "artifact.bin", b"concurrent")
    errors: list[BaseException] = []
    results: list[str] = []

    def _worker(index: int) -> None:
        try:
            result = DocumentWorkerRunner(timeout_seconds=20).run_echo_hash(
                artifact_path=artifact,
                run_directory=tmp_path / f"run-concurrent-{index}",
                run_id=f"run-echo-concurrent-{index}",
            )
            results.append(result.response.run_id)
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=_worker, args=(index,)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert errors == []
    assert sorted(results) == ["run-echo-concurrent-0", "run-echo-concurrent-1"]
    assert (tmp_path / "run-concurrent-0" / "echo_hash.json").read_bytes() != b""
    assert (tmp_path / "run-concurrent-1" / "echo_hash.json").read_bytes() != b""
    # Directories remain distinct; no cross-write.
    assert "run-echo-concurrent-0" in (tmp_path / "run-concurrent-0" / "echo_hash.json").read_text()
    assert "run-echo-concurrent-1" in (tmp_path / "run-concurrent-1" / "echo_hash.json").read_text()


def test_runner_rejects_symlink_artifact(tmp_path: Path) -> None:
    target = _write_artifact(tmp_path / "real.bin", b"symlink")
    link = tmp_path / "link.bin"
    link.symlink_to(target)
    with pytest.raises(DocumentWorkerRunnerError) as raised:
        DocumentWorkerRunner().run_echo_hash(
            artifact_path=link,
            run_directory=tmp_path / "run-symlink",
            run_id="run-echo-symlink",
        )
    assert raised.value.code == "artifact_symlink_rejected"
