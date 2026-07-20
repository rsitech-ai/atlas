from __future__ import annotations

import subprocess
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
        if command == "pg_ctl" and "stop" in args:
            self.running = False
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
