from __future__ import annotations

import os
import shlex
from pathlib import Path

import pytest
from rsi_atlas_ingestion.worker_runner import DocumentWorkerRunner, DocumentWorkerRunnerError


def _write_executable(path: Path, script: str) -> Path:
    path.write_text(script, encoding="utf-8")
    os.chmod(path, 0o700)
    return path


def _sandbox_shim(tmp_path: Path) -> Path:
    return _write_executable(
        tmp_path / "sandbox-shim",
        """#!/bin/sh
if [ "$1" != "-f" ] || [ "$2" = "" ]; then
    exit 64
fi
shift 2
exec "$@"
""",
    )


def _artifact(tmp_path: Path) -> Path:
    path = tmp_path / "artifact.bin"
    path.write_bytes(b"worker-supervision-boundary")
    os.chmod(path, 0o600)
    return path


def _assert_partial_output_is_cleaned(run_directory: Path) -> None:
    assert sorted(path.name for path in run_directory.iterdir()) == ["document-worker.rendered.sb"]


def test_runner_rejects_stdout_limit_plus_one_and_cleans_partial_output(tmp_path: Path) -> None:
    worker = _write_executable(
        tmp_path / "overflow-worker",
        """#!/bin/sh
cat >/dev/null
printf partial > partial.out
dd if=/dev/zero bs=65536 count=4 2>/dev/null
""",
    )
    run_directory = tmp_path / "run-overflow"

    runner = DocumentWorkerRunner(
        python_executable=worker,
        sandbox_executable=_sandbox_shim(tmp_path),
        timeout_seconds=5,
        max_stdout_bytes=64 * 1024,
    )

    with pytest.raises(DocumentWorkerRunnerError) as raised:
        runner.run_echo_hash(
            artifact_path=_artifact(tmp_path),
            run_directory=run_directory,
            run_id="worker-overflow-001",
        )

    assert raised.value.code == "worker_output_too_large"
    _assert_partial_output_is_cleaned(run_directory)


def test_runner_times_out_kills_worker_group_and_cleans_partial_output(tmp_path: Path) -> None:
    pid_path = tmp_path / "worker.pid"
    worker = _write_executable(
        tmp_path / "timeout-worker",
        f"""#!/bin/sh
printf '%s\\n' "$$" > {shlex.quote(str(pid_path))}
printf partial > partial.out
cat >/dev/null
sleep 30
""",
    )
    run_directory = tmp_path / "run-timeout"

    runner = DocumentWorkerRunner(
        python_executable=worker,
        sandbox_executable=_sandbox_shim(tmp_path),
        timeout_seconds=1,
    )

    with pytest.raises(DocumentWorkerRunnerError) as raised:
        runner.run_echo_hash(
            artifact_path=_artifact(tmp_path),
            run_directory=run_directory,
            run_id="worker-timeout-001",
        )

    assert raised.value.code == "worker_timeout"
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_path.read_text(encoding="utf-8")), 0)
    _assert_partial_output_is_cleaned(run_directory)
