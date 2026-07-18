from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import socket
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path
from types import ModuleType

import pytest

VERIFIER_PATH = Path("infra/security/verify_zero_egress.py")


def _argv_fingerprint(argv: list[str]) -> dict[str, object]:
    canonical = json.dumps(argv, ensure_ascii=False, separators=(",", ":")).encode()
    return {"count": len(argv), "sha256": hashlib.sha256(canonical).hexdigest()}


def _load_verifier() -> ModuleType:
    specification = importlib.util.spec_from_file_location(
        "atlas_zero_egress_verifier", VERIFIER_PATH
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    specification.loader.exec_module(module)
    return module


def _run_verifier(*arguments: str, timeout: float = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VERIFIER_PATH), *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_real_macos_sandbox_denies_dns_and_external_tcp_but_allows_exact_local_socket() -> None:
    result = _run_verifier("--", sys.executable, "-c", "raise SystemExit(0)")

    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout)
    assert evidence["schema_version"] == "1.0.0"
    assert evidence["evidence_label"] == "development_component_evidence"
    assert evidence["profile"] == "offline"
    assert evidence["result"] == "passed"
    assert evidence["canaries"] == {
        "external_tcp_denied": True,
        "local_unix_socket_allowed": True,
        "mdns_responder_socket_denied": True,
    }
    assert evidence["target"]["exit_status"] == 0
    assert evidence["target"]["timed_out"] is False
    assert evidence["sandbox_profile_sha256"]
    assert evidence["executable"]["path"] == str(Path(sys.executable).resolve())
    assert len(evidence["executable"]["sha256"]) == 64


def test_argv_boundary_is_not_evaluated_by_a_shell(tmp_path: Path) -> None:
    marker = tmp_path / "shell-evaluated"
    literal = f"literal; touch {marker}"
    code = "import sys; raise SystemExit(0 if sys.argv[1].startswith('literal;') else 9)"

    result = _run_verifier("--", sys.executable, "-c", code, literal)

    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout)
    assert "argv" not in evidence
    assert evidence["argv_fingerprint"] == _argv_fingerprint([sys.executable, "-c", code, literal])
    assert literal not in result.stdout
    assert not marker.exists()


def test_command_compatibility_option_uses_shlex_without_shell(tmp_path: Path) -> None:
    marker = tmp_path / "compat-shell-evaluated"
    command = f'{sys.executable} -c "raise SystemExit(0)" "; touch {marker}"'

    result = _run_verifier("--command", command)

    assert result.returncode == 0, result.stderr
    assert not marker.exists()


@pytest.mark.parametrize(
    "argument",
    [
        "--password=private-value",
        "--api-key=private-value",
        "Authorization: Bearer private-value",
        "PRIVATE_KEY=private-value",
    ],
)
def test_sensitive_argv_is_rejected_without_echo(argument: str) -> None:
    result = _run_verifier("--", sys.executable, "-c", "pass", argument)

    assert result.returncode != 0
    assert "sensitive argv is prohibited" in result.stderr
    assert "private-value" not in result.stdout
    assert "private-value" not in result.stderr


def test_missing_sandbox_support_fails_closed(tmp_path: Path) -> None:
    verifier = _load_verifier()
    stdout = io.StringIO()
    stderr = io.StringIO()

    status = verifier.main(
        ["--", sys.executable, "-c", "pass"],
        stdout=stdout,
        stderr=stderr,
        sandbox_executable=tmp_path / "missing-sandbox-exec",
    )

    assert status == 1
    assert "sandbox support unavailable" in stderr.getvalue()
    assert "development_component_evidence" in stdout.getvalue()


def test_missing_mdns_responder_discriminator_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verifier = _load_verifier()
    stdout = io.StringIO()
    stderr = io.StringIO()
    monkeypatch.setattr(verifier, "MDNS_RESPONDER", Path("/missing/mDNSResponder"))

    status = verifier.main(
        ["--", sys.executable, "-c", "pass"],
        stdout=stdout,
        stderr=stderr,
    )

    assert status == 1
    assert "DNS denial discriminator unavailable" in stderr.getvalue()


def test_rejected_sandbox_profile_fails_closed(tmp_path: Path) -> None:
    verifier = _load_verifier()
    rejected = tmp_path / "sandbox-exec"
    rejected.write_text("#!/usr/bin/python3\nraise SystemExit(64)\n")
    rejected.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    stdout = io.StringIO()
    stderr = io.StringIO()

    status = verifier.main(
        ["--", sys.executable, "-c", "pass"],
        stdout=stdout,
        stderr=stderr,
        sandbox_executable=rejected,
    )

    assert status == 1
    assert "sandbox profile rejected" in stderr.getvalue()


def test_canary_failure_fails_closed(tmp_path: Path) -> None:
    verifier = _load_verifier()
    passthrough = tmp_path / "sandbox-exec"
    passthrough.write_text(
        "#!/usr/bin/python3\n"
        "import os, sys\n"
        "separator = sys.argv.index('--')\n"
        "os.execv(sys.argv[separator + 1], sys.argv[separator + 1:])\n"
    )
    passthrough.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    stdout = io.StringIO()
    stderr = io.StringIO()

    status = verifier.main(
        ["--", sys.executable, "-c", "pass"],
        stdout=stdout,
        stderr=stderr,
        sandbox_executable=passthrough,
    )

    assert status == 1
    assert "network denial canary failed" in stderr.getvalue()


def test_evidence_write_failure_fails_closed() -> None:
    verifier = _load_verifier()

    class BrokenOutput(io.StringIO):
        def write(self, value: str) -> int:
            raise OSError("closed output")

    stderr = io.StringIO()
    status = verifier.main(
        ["--", sys.executable, "-c", "pass"],
        stdout=BrokenOutput(),
        stderr=stderr,
    )

    assert status == 1
    assert "evidence could not be recorded" in stderr.getvalue()


def test_target_exit_64_is_recorded_as_target_failure_not_profile_rejection() -> None:
    result = _run_verifier("--", sys.executable, "-c", "raise SystemExit(64)")

    assert result.returncode == 1
    assert "sandbox profile rejected" not in result.stderr
    evidence = json.loads(result.stdout)
    assert evidence["target"] == {"exit_status": 64, "timed_out": False}


def test_resolved_executable_identity_matches_executed_path(tmp_path: Path) -> None:
    executable_alias = tmp_path / "target-alias"
    executable_alias.symlink_to("/usr/bin/true")

    result = _run_verifier("--", str(executable_alias))

    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout)
    assert evidence["argv_fingerprint"] == _argv_fingerprint([str(executable_alias)])
    assert evidence["executable"]["path"] == str(Path("/usr/bin/true").resolve())
    assert (
        evidence["executable"]["execution_binding"]
        == "opened_descriptor_hash_with_path_revalidation"
    )
    assert evidence["executable"]["limitation"] == "path_execution_not_kernel_bound"
    assert isinstance(evidence["executable"]["device"], int)
    assert isinstance(evidence["executable"]["inode"], int)


def test_executable_replacement_during_target_fails_closed(tmp_path: Path) -> None:
    executable = tmp_path / "replace-self"
    replacement = tmp_path / "original"
    executable.write_text(
        "#!/usr/bin/python3\n"
        "import pathlib,sys\n"
        "path=pathlib.Path(sys.argv[1])\n"
        "path.rename(path.with_name('original'))\n"
        "path.write_text('#!/usr/bin/python3\\nraise SystemExit(0)\\n')\n"
    )
    executable.chmod(0o700)

    result = _run_verifier("--", str(executable), str(executable))

    assert result.returncode == 1
    assert "executable path identity changed" in result.stderr
    assert json.loads(result.stdout)["result"] == "failed"
    assert replacement.exists()


def test_child_start_failure_is_stable_and_has_no_traceback(tmp_path: Path) -> None:
    verifier = _load_verifier()
    invalid_executable = tmp_path / "sandbox-exec"
    invalid_executable.write_text("not an executable format")
    invalid_executable.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    stdout = io.StringIO()
    stderr = io.StringIO()

    status = verifier.main(
        ["--", sys.executable, "-c", "pass"],
        stdout=stdout,
        stderr=stderr,
        sandbox_executable=invalid_executable,
    )

    assert status == 1
    assert "sandbox child could not start" in stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()


def test_argument_parser_failure_records_fail_closed_evidence() -> None:
    result = _run_verifier("--timeout-seconds", "not-a-number")

    assert result.returncode == 1
    assert json.loads(result.stdout)["result"] == "failed"
    assert "verification arguments are invalid" in result.stderr


def test_timeout_terminates_only_the_target_process_group(tmp_path: Path) -> None:
    marker = tmp_path / "orphan-marker"
    code = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c',"
        f'"import time,pathlib; time.sleep(1); pathlib.Path({str(marker)!r}).touch()"]); '
        "time.sleep(10)"
    )

    result = _run_verifier(
        "--timeout-seconds",
        "0.2",
        "--",
        sys.executable,
        "-c",
        code,
        timeout=10,
    )

    assert result.returncode != 0
    evidence = json.loads(result.stdout)
    assert evidence["target"]["timed_out"] is True
    time.sleep(1.2)
    assert not marker.exists()


def test_timeout_terminates_detached_child_descendant(tmp_path: Path) -> None:
    marker = tmp_path / "detached-orphan-marker"
    code = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c',"
        f'"import time,pathlib; time.sleep(1); pathlib.Path({str(marker)!r}).touch()"], '
        "start_new_session=True); time.sleep(10)"
    )

    result = _run_verifier(
        "--timeout-seconds",
        "0.3",
        "--",
        sys.executable,
        "-c",
        code,
        timeout=10,
    )

    assert result.returncode != 0
    assert json.loads(result.stdout)["target"]["timed_out"] is True
    time.sleep(1.2)
    assert not marker.exists()


def test_allowed_unix_socket_replacement_during_target_fails_closed() -> None:
    with tempfile.TemporaryDirectory(prefix="as-", dir=tempfile.gettempdir()) as directory:
        root = Path(directory).resolve()
        root.chmod(0o700)
        socket_path = root / "allowed.sock"
        with closing(socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)) as server:
            server.bind(str(socket_path))
            socket_path.chmod(0o600)
            code = (
                "import os,socket,sys; path=sys.argv[1]; os.unlink(path); "
                "replacement=socket.socket(socket.AF_UNIX); replacement.bind(path); "
                "os.chmod(path,0o600); replacement.close()"
            )

            result = _run_verifier(
                "--allow-unix-socket",
                str(socket_path),
                "--",
                sys.executable,
                "-c",
                code,
                str(socket_path),
            )

        assert result.returncode == 1
        assert "Unix socket identity changed" in result.stderr
        socket_path.unlink(missing_ok=True)


def test_evidence_is_privacy_safe_and_has_no_captured_payload_or_environment() -> None:
    result = _run_verifier("--", "/usr/bin/true")

    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout)
    assert "environment" not in evidence
    assert "argv" not in evidence
    assert "stdout" not in evidence["target"]
    assert "stderr" not in evidence["target"]
    assert set(evidence) == {
        "argv_fingerprint",
        "canaries",
        "end_time",
        "evidence_label",
        "executable",
        "profile",
        "result",
        "sandbox_profile_sha256",
        "schema_version",
        "start_time",
        "target",
    }


def test_unlabeled_argument_value_is_never_persisted_in_evidence() -> None:
    opaque_value = "opaque-value-9384"
    result = _run_verifier("--", sys.executable, "-c", "pass", opaque_value)

    assert result.returncode == 0, result.stderr
    assert opaque_value not in result.stdout
    assert json.loads(result.stdout)["argv_fingerprint"] == _argv_fingerprint(
        [sys.executable, "-c", "pass", opaque_value]
    )
