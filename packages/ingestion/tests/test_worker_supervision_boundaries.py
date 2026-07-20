from __future__ import annotations

import os
import shlex
import time
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


def _assert_worker_group_is_gone(leader_pid_path: Path, child_pid_path: Path) -> None:
    leader_pid = int(leader_pid_path.read_text(encoding="utf-8"))
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(leader_pid, 0)
            leader_alive = True
        except ProcessLookupError:
            leader_alive = False
        try:
            os.kill(child_pid, 0)
            child_alive = True
        except ProcessLookupError:
            child_alive = False
        try:
            os.killpg(leader_pid, 0)
            group_alive = True
        except ProcessLookupError:
            group_alive = False
        if not leader_alive and not child_alive and not group_alive:
            break
        time.sleep(0.02)
    else:
        pytest.fail("worker process group remained alive after runner failure")
    with pytest.raises(ProcessLookupError):
        os.kill(leader_pid, 0)
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
    with pytest.raises(ProcessLookupError):
        os.killpg(leader_pid, 0)


def test_runner_rejects_stdout_at_exact_limit_plus_one_and_kills_worker_group(
    tmp_path: Path,
) -> None:
    leader_pid_path = tmp_path / "overflow-leader.pid"
    child_pid_path = tmp_path / "overflow-child.pid"
    worker = _write_executable(
        tmp_path / "overflow-worker",
        f"""#!/bin/sh
sleep 30 &
child_pid=$!
printf '%s\\n' "$$" > {shlex.quote(str(leader_pid_path))}
printf '%s\\n' "$child_pid" > {shlex.quote(str(child_pid_path))}
cat >/dev/null
printf partial > partial.out
dd if=/dev/zero bs=65536 count=1 2>/dev/null
printf x
wait "$child_pid"
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
    _assert_worker_group_is_gone(leader_pid_path, child_pid_path)
    _assert_partial_output_is_cleaned(run_directory)


def test_runner_times_out_kills_worker_group_and_cleans_partial_output(tmp_path: Path) -> None:
    leader_pid_path = tmp_path / "timeout-leader.pid"
    child_pid_path = tmp_path / "timeout-child.pid"
    worker = _write_executable(
        tmp_path / "timeout-worker",
        f"""#!/bin/sh
sleep 30 &
child_pid=$!
printf '%s\\n' "$$" > {shlex.quote(str(leader_pid_path))}
printf '%s\\n' "$child_pid" > {shlex.quote(str(child_pid_path))}
printf partial > partial.out
cat >/dev/null
wait "$child_pid"
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
    _assert_worker_group_is_gone(leader_pid_path, child_pid_path)
    _assert_partial_output_is_cleaned(run_directory)


def test_runner_timeout_escalates_when_descendant_ignores_sigterm(tmp_path: Path) -> None:
    leader_pid_path = tmp_path / "ignoring-leader.pid"
    child_pid_path = tmp_path / "ignoring-child.pid"
    worker = _write_executable(
        tmp_path / "ignoring-term-worker",
        f"""#!/bin/sh
trap 'exit 0' TERM
(
    trap '' TERM
    exec sleep 30
) &
child_pid=$!
printf '%s\\n' "$$" > {shlex.quote(str(leader_pid_path))}
printf '%s\\n' "$child_pid" > {shlex.quote(str(child_pid_path))}
printf partial > partial.out
cat >/dev/null
wait "$child_pid"
""",
    )
    run_directory = tmp_path / "run-ignoring-term"

    runner = DocumentWorkerRunner(
        python_executable=worker,
        sandbox_executable=_sandbox_shim(tmp_path),
        timeout_seconds=1,
    )

    with pytest.raises(DocumentWorkerRunnerError) as raised:
        runner.run_echo_hash(
            artifact_path=_artifact(tmp_path),
            run_directory=run_directory,
            run_id="worker-ignoring-term-001",
        )

    assert raised.value.code == "worker_timeout"
    _assert_worker_group_is_gone(leader_pid_path, child_pid_path)
    _assert_partial_output_is_cleaned(run_directory)
