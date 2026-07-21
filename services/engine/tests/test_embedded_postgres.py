from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from rsi_atlas_engine.embedded_postgres import EmbeddedPostgres


class RecordingRunner:
    def __init__(self, data_directory: Path) -> None:
        self.data_directory = data_directory
        self.calls: list[tuple[tuple[str, ...], dict[str, str]]] = []
        self.running = False

    def __call__(
        self,
        arguments: Sequence[str],
        *,
        environment: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        args = tuple(arguments)
        env = dict(environment)
        self.calls.append((args, env))
        command = Path(args[0]).name
        if command == "initdb":
            self.data_directory.mkdir()
            (self.data_directory / "PG_VERSION").write_text("17\n", encoding="utf-8")
        if command == "pg_controldata":
            return subprocess.CompletedProcess(
                args,
                0,
                stdout="Data page checksum version:           1\n",
                stderr="",
            )
        if command == "pg_ctl" and "status" in args:
            return subprocess.CompletedProcess(args, 0 if self.running else 3, "", "")
        if command == "pg_ctl" and "start" in args:
            self.running = True
            (self.data_directory / "postmaster.pid").write_text(
                "4242\n"
                f"{self.data_directory.resolve()}\n"
                "1784592000\n"
                "5432\n"
                f"{Path(env['PGHOST']).resolve()}\n"
                "\n"
                "\n"
                "ready\n",
                encoding="utf-8",
            )
        if command == "pg_ctl" and "stop" in args:
            self.running = False
            (self.data_directory / "postmaster.pid").unlink(missing_ok=True)
        if command == "psql" and "SELECT 1 FROM pg_database" in args[-1]:
            return subprocess.CompletedProcess(args, 0, stdout="\n", stderr="")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


def _runtime_tree(root: Path) -> Path:
    postgresql = root / "postgresql"
    binary_root = postgresql / "bin"
    binary_root.mkdir(parents=True)
    for name in ("createdb", "initdb", "pg_controldata", "pg_ctl", "postgres", "psql"):
        binary = binary_root / name
        binary.write_text("binary\n", encoding="utf-8")
        binary.chmod(0o700)
    extension = postgresql / "share" / "postgresql@17" / "extension"
    extension.mkdir(parents=True)
    (extension / "vector.control").write_text("default_version = '0.8.5'\n")
    vector = postgresql / "lib" / "postgresql" / "vector.dylib"
    vector.parent.mkdir(parents=True)
    vector.write_bytes(b"vector")
    return root


def test_embedded_postgres_initializes_uds_only_cluster_and_bootstraps_vector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime_tree(tmp_path / "runtime")
    data_root = tmp_path / "data"
    data_root.mkdir(mode=0o700)
    data_directory = data_root / "postgres" / "data"
    runner = RecordingRunner(data_directory)
    monkeypatch.setenv("PGPASSWORD", "must-not-leak")
    monkeypatch.setenv("DYLD_INSERT_LIBRARIES", "/tmp/injected.dylib")
    postgres = EmbeddedPostgres(runtime_root=runtime, data_root=data_root, runner=runner)

    postgres.start()

    names = [Path(arguments[0]).name for arguments, _ in runner.calls]
    assert names == [
        "initdb",
        "pg_controldata",
        "pg_ctl",
        "pg_ctl",
        "psql",
        "createdb",
        "psql",
    ]
    start_arguments = next(
        arguments
        for arguments, _ in runner.calls
        if Path(arguments[0]).name == "pg_ctl" and "start" in arguments
    )
    options = start_arguments[start_arguments.index("--options") + 1]
    assert "listen_addresses=''" in options
    assert "unix_socket_permissions=0700" in options
    assert str(data_root / "postgres" / "socket") in options
    assert all("PGPASSWORD" not in environment for _, environment in runner.calls)
    assert all("DYLD_INSERT_LIBRARIES" not in environment for _, environment in runner.calls)
    assert all(
        environment["PGHOST"] == str(data_root / "postgres" / "socket")
        for _, environment in runner.calls
    )

    postgres.stop()
    assert Path(runner.calls[-1][0][0]).name == "pg_ctl"
    assert "stop" in runner.calls[-1][0]
    assert not runner.running


def test_embedded_postgres_rejects_missing_runtime_and_unsafe_data_root(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir(mode=0o755)
    with pytest.raises(ValueError, match="owner-private"):
        EmbeddedPostgres(runtime_root=tmp_path / "missing", data_root=data_root)


def test_embedded_postgres_fails_closed_when_checksums_are_disabled(tmp_path: Path) -> None:
    runtime = _runtime_tree(tmp_path / "runtime")
    data_root = tmp_path / "data"
    data_root.mkdir(mode=0o700)
    data_directory = data_root / "postgres" / "data"
    runner = RecordingRunner(data_directory)

    def no_checksums(
        arguments: Sequence[str],
        *,
        environment: Mapping[str, str],
    ) -> subprocess.CompletedProcess[str]:
        result = runner(arguments, environment=environment)
        if Path(arguments[0]).name == "pg_controldata":
            return subprocess.CompletedProcess(
                arguments,
                0,
                stdout="Data page checksum version:           0\n",
                stderr="",
            )
        return result

    postgres = EmbeddedPostgres(
        runtime_root=runtime,
        data_root=data_root,
        runner=no_checksums,
    )

    with pytest.raises(RuntimeError, match="checksums"):
        postgres.start()
    assert not runner.running


def test_embedded_postgres_reclaims_only_a_matching_owned_orphan(tmp_path: Path) -> None:
    runtime = _runtime_tree(tmp_path / "runtime")
    data_root = tmp_path / "data"
    data_root.mkdir(mode=0o700)
    data_directory = data_root / "postgres" / "data"
    runner = RecordingRunner(data_directory)
    crashed = EmbeddedPostgres(runtime_root=runtime, data_root=data_root, runner=runner)
    crashed.start()
    crashed._release_ownership_lock()
    crashed._started_here = False

    restarted = EmbeddedPostgres(runtime_root=runtime, data_root=data_root, runner=runner)
    restarted.start()

    pg_ctl_actions = [
        arguments[-1]
        for arguments, _ in runner.calls
        if Path(arguments[0]).name == "pg_ctl" and arguments[-1] in {"start", "stop"}
    ]
    assert pg_ctl_actions == ["start", "stop", "start"]
    restarted.stop()
    assert not runner.running


def test_embedded_postgres_refuses_an_unmarked_running_cluster(tmp_path: Path) -> None:
    runtime = _runtime_tree(tmp_path / "runtime")
    data_root = tmp_path / "data"
    data_root.mkdir(mode=0o700)
    data_directory = data_root / "postgres" / "data"
    runner = RecordingRunner(data_directory)
    data_directory.mkdir(parents=True)
    (data_directory / "PG_VERSION").write_text("17\n", encoding="utf-8")
    runner.running = True
    postgres = EmbeddedPostgres(runtime_root=runtime, data_root=data_root, runner=runner)

    with pytest.raises(RuntimeError, match="no trusted RSI Atlas owner"):
        postgres.start()

    assert runner.running


@pytest.mark.skipif(sys.platform != "darwin", reason="bundled release runtime is macOS-only")
def test_real_engine_crash_orphan_is_reclaimed_and_restartable() -> None:
    root = Path(__file__).resolve().parents[3]
    runtime = root / "dist" / "runtime-payload" / "Contents" / "Resources" / "runtime"
    if not (runtime / "postgresql" / "bin" / "postgres").is_file():
        pytest.skip("real release runtime payload is not staged")
    temporary = Path(tempfile.mkdtemp(prefix="rsi-atlas-crash-", dir="/private/tmp"))
    data_root = temporary / "data"
    data_root.mkdir(mode=0o700)
    read_descriptor, write_descriptor = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(read_descriptor)
        exit_code = 0
        try:
            EmbeddedPostgres(runtime_root=runtime, data_root=data_root).start()
            os.write(write_descriptor, b"ready")
        except Exception:
            exit_code = 1
            os.write(write_descriptor, b"error")
        finally:
            os.close(write_descriptor)
        os._exit(exit_code)
    os.close(write_descriptor)
    restarted: EmbeddedPostgres | None = None
    pg_ctl = runtime / "postgresql" / "bin" / "pg_ctl"
    environment = EmbeddedPostgres(runtime_root=runtime, data_root=data_root)._environment()
    try:
        assert os.read(read_descriptor, 5) == b"ready"
        _, child_status = os.waitpid(child, 0)
        assert os.waitstatus_to_exitcode(child_status) == 0
        orphan_status = subprocess.run(
            [str(pg_ctl), "--pgdata", str(data_root / "postgres" / "data"), "status"],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        assert orphan_status.returncode == 0

        restarted = EmbeddedPostgres(runtime_root=runtime, data_root=data_root)
        restarted.start()
        psql = runtime / "postgresql" / "bin" / "psql"
        vector = subprocess.run(
            [
                str(psql),
                "--dbname=atlas",
                "--tuples-only",
                "--no-align",
                "--command",
                "SELECT extversion FROM pg_extension WHERE extname='vector'",
            ],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        assert vector.stdout.strip() == "0.8.5"
        restarted.stop()
        restarted = None
        stopped = subprocess.run(
            [str(pg_ctl), "--pgdata", str(data_root / "postgres" / "data"), "status"],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        assert stopped.returncode == 3
    finally:
        os.close(read_descriptor)
        if restarted is not None:
            restarted.stop()
        subprocess.run(
            [
                str(pg_ctl),
                "--pgdata",
                str(data_root / "postgres" / "data"),
                "--mode=immediate",
                "stop",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        shutil.rmtree(temporary, ignore_errors=True)
