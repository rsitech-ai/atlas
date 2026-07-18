from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn, TextIO

from rsi_atlas_security import NetworkPolicy, ProcessRole

SANDBOX_EXECUTABLE = Path("/usr/bin/sandbox-exec")
MDNS_RESPONDER = Path("/private/var/run/mDNSResponder")
EVIDENCE_LABEL = "development_component_evidence"
MAX_ARGUMENT_COUNT = 256
MAX_ARGUMENT_BYTES = 65_536
SAFE_PROFILE_PATH = re.compile(r"^/[A-Za-z0-9._/-]+$")
SENSITIVE_ARGUMENT = re.compile(
    r"(?i)(?:password|passwd|api[-_]?key|private(?:[-_]?key)?|authorization|credential|"
    r"secret|token|payload|document[-_]?content|report[-_]?content|prompt|trace[-_]?content)"
    r"(?:\s|=|:|$)"
)


class VerificationError(RuntimeError):
    pass


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise VerificationError("executable identity could not be recorded") from error
    return digest.hexdigest()


def _resolve_executable(argv: Sequence[str]) -> tuple[str, str]:
    executable = argv[0]
    candidate = executable if os.path.isabs(executable) else shutil.which(executable)
    if candidate is None:
        raise VerificationError("target executable is unavailable")
    path = Path(candidate).resolve(strict=True)
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode) or not os.access(path, os.X_OK):
        raise VerificationError("target executable is invalid")
    return str(path), _sha256_file(path)


def _validate_argv(argv: Sequence[str]) -> tuple[str, ...]:
    if not argv or len(argv) > MAX_ARGUMENT_COUNT:
        raise VerificationError("target argv is invalid")
    encoded_total = 0
    validated: list[str] = []
    for argument in argv:
        if not isinstance(argument, str) or not argument or "\0" in argument:
            raise VerificationError("target argv is invalid")
        if any(ord(character) < 32 and character not in {"\t"} for character in argument):
            raise VerificationError("target argv is invalid")
        if SENSITIVE_ARGUMENT.search(argument):
            raise VerificationError("sensitive argv is prohibited")
        encoded_total += len(argument.encode("utf-8"))
        validated.append(argument)
    if encoded_total > MAX_ARGUMENT_BYTES:
        raise VerificationError("target argv is invalid")
    return tuple(validated)


def _safe_socket_paths(paths: Sequence[str]) -> tuple[str, ...]:
    if len(paths) != len(set(paths)):
        raise VerificationError("duplicate Unix socket allowance")
    validated: list[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not SAFE_PROFILE_PATH.fullmatch(raw_path):
            raise VerificationError("Unix socket allowance is not profile-safe")
        try:
            decision = NetworkPolicy.offline(unix_socket_paths=[path]).authorize(
                role=ProcessRole.ENGINE,
                unix_socket_path=path,
            )
        except ValueError as error:
            raise VerificationError("Unix socket allowance failed validation") from error
        if not decision.allowed or decision.canonical_destination is None:
            raise VerificationError("Unix socket allowance failed validation")
        validated.append(decision.canonical_destination)
    return tuple(sorted(validated))


def _sandbox_profile(socket_paths: Sequence[str]) -> str:
    rules = ["(version 1)", "(allow default)", "(deny network*)"]
    for path in socket_paths:
        if not SAFE_PROFILE_PATH.fullmatch(path):
            raise VerificationError("Unix socket allowance is not profile-safe")
        rules.append(f'(allow network-outbound (literal "{path}"))')
    return "\n".join(rules) + "\n"


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError as error:
        raise VerificationError("sandbox child cleanup failed") from error
    try:
        process.wait(timeout=0.5)
        return
    except subprocess.TimeoutExpired:
        pass
    except OSError as error:
        raise VerificationError("sandbox child cleanup failed") from error
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError as error:
        raise VerificationError("sandbox child cleanup failed") from error
    try:
        process.wait(timeout=1)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VerificationError("sandbox child cleanup failed") from error


def _run_sandboxed(
    *,
    sandbox_executable: Path,
    profile: str,
    argv: Sequence[str],
    timeout_seconds: float,
) -> tuple[int | None, bool]:
    try:
        process = subprocess.Popen(
            [str(sandbox_executable), "-p", profile, "--", *argv],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        raise VerificationError("sandbox child could not start") from error
    try:
        return process.wait(timeout=timeout_seconds), False
    except subprocess.TimeoutExpired:
        _terminate_process_group(process)
        return None, True
    except OSError as error:
        _terminate_process_group(process)
        raise VerificationError("sandbox child wait failed") from error


MDNS_CANARY = (
    "import errno,socket,sys; client=socket.socket(socket.AF_UNIX); client.settimeout(1); "
    "\ntry: client.connect(sys.argv[1])"
    "\nexcept PermissionError as error: raise SystemExit(0 if error.errno == errno.EPERM else 11)"
    "\nexcept OSError: raise SystemExit(12)"
    "\nraise SystemExit(10)"
)
TCP_CANARY = (
    "import errno,socket; "
    "\ntry: socket.create_connection(('1.1.1.1', 443), 1)"
    "\nexcept PermissionError as error: raise SystemExit(0 if error.errno == errno.EPERM else 11)"
    "\nexcept OSError: raise SystemExit(12)"
    "\nraise SystemExit(10)"
)
UNIX_CANARY = (
    "import socket,sys; "
    "client=socket.socket(socket.AF_UNIX); client.settimeout(1); "
    "client.connect(sys.argv[1]); client.sendall(b'atlas'); "
    "raise SystemExit(0 if client.recv(5)==b'allow' else 12)"
)


def _run_denial_canary(
    *,
    sandbox_executable: Path,
    profile: str,
    code: str,
    arguments: Sequence[str] = (),
) -> bool:
    status, timed_out = _run_sandboxed(
        sandbox_executable=sandbox_executable,
        profile=profile,
        argv=[sys.executable, "-c", code, *arguments],
        timeout_seconds=3,
    )
    if timed_out or status != 0:
        raise VerificationError("network denial canary failed")
    return True


def _validate_profile(*, sandbox_executable: Path, profile: str) -> None:
    status, timed_out = _run_sandboxed(
        sandbox_executable=sandbox_executable,
        profile=profile,
        argv=["/usr/bin/true"],
        timeout_seconds=3,
    )
    if timed_out or status != 0:
        raise VerificationError("sandbox profile rejected")


def _validate_mdns_discriminator() -> None:
    try:
        metadata = MDNS_RESPONDER.stat(follow_symlinks=False)
    except OSError as error:
        raise VerificationError("DNS denial discriminator unavailable") from error
    if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != 0:
        raise VerificationError("DNS denial discriminator unavailable")


def _run_unix_canary(
    *,
    sandbox_executable: Path,
    target_socket_paths: Sequence[str],
) -> bool:
    with tempfile.TemporaryDirectory(prefix="atlas-egress-", dir="/private/tmp") as directory:
        root = Path(directory)
        root.chmod(0o700)
        socket_path = root / "canary.sock"
        received = bytearray()
        server_error: list[BaseException] = []
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(socket_path))
            socket_path.chmod(0o600)
            server.listen(1)
            server.settimeout(3)

            def serve() -> None:
                try:
                    connection, _ = server.accept()
                    with connection:
                        received.extend(connection.recv(5))
                        connection.sendall(b"allow")
                except BaseException as error:  # pragma: no cover - surfaced below
                    server_error.append(error)

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            profile = _sandbox_profile([*target_socket_paths, str(socket_path)])
            status, timed_out = _run_sandboxed(
                sandbox_executable=sandbox_executable,
                profile=profile,
                argv=[sys.executable, "-c", UNIX_CANARY, str(socket_path)],
                timeout_seconds=3,
            )
            thread.join(timeout=3)
        if timed_out or status != 0 or thread.is_alive() or server_error or received != b"atlas":
            raise VerificationError("local Unix socket canary failed")
    return True


def _failure_evidence(*, start_time: str, argv: Sequence[str]) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "evidence_label": EVIDENCE_LABEL,
        "profile": "offline",
        "argv": list(argv),
        "executable": {"path": None, "sha256": None},
        "sandbox_profile_sha256": None,
        "start_time": start_time,
        "end_time": _timestamp(),
        "canaries": {
            "external_tcp_denied": False,
            "local_unix_socket_allowed": False,
            "mdns_responder_socket_denied": False,
        },
        "target": {"exit_status": None, "timed_out": False},
        "result": "failed",
    }


def _record_evidence(evidence: dict[str, Any], stdout: TextIO) -> None:
    try:
        json.dump(evidence, stdout, sort_keys=True, separators=(",", ":"))
        stdout.write("\n")
        stdout.flush()
    except (OSError, TypeError, ValueError) as error:
        raise VerificationError("evidence could not be recorded") from error


class _FailClosedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise VerificationError("verification arguments are invalid")


def _parser() -> argparse.ArgumentParser:
    parser = _FailClosedArgumentParser(
        description="Record macOS development-component zero-egress evidence"
    )
    parser.add_argument("--command", help="Compatibility command parsed with shlex.split")
    parser.add_argument("--allow-unix-socket", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    return parser


def _command_from_arguments(arguments: argparse.Namespace) -> tuple[str, ...]:
    remainder = list(arguments.argv)
    if remainder[:1] == ["--"]:
        remainder = remainder[1:]
    if arguments.command is not None and remainder:
        raise VerificationError("choose either --command or an argv boundary")
    if arguments.command is not None:
        try:
            remainder = shlex.split(arguments.command, posix=True)
        except ValueError as error:
            raise VerificationError("compatibility command is invalid") from error
    return _validate_argv(remainder)


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    sandbox_executable: Path = SANDBOX_EXECUTABLE,
) -> int:
    start_time = _timestamp()
    safe_argv: tuple[str, ...] = ()
    try:
        arguments = _parser().parse_args(argv)
        if not 0.1 <= arguments.timeout_seconds <= 60:
            raise VerificationError("target timeout is invalid")
        safe_argv = _command_from_arguments(arguments)
        if not sandbox_executable.is_file() or not os.access(sandbox_executable, os.X_OK):
            raise VerificationError("sandbox support unavailable")
        socket_paths = _safe_socket_paths(arguments.allow_unix_socket)
        profile = _sandbox_profile(socket_paths)
        profile_hash = hashlib.sha256(profile.encode("utf-8")).hexdigest()
        executable_path, executable_hash = _resolve_executable(safe_argv)
        _validate_mdns_discriminator()
        _validate_profile(sandbox_executable=sandbox_executable, profile=profile)
        mdns_denied = _run_denial_canary(
            sandbox_executable=sandbox_executable,
            profile=profile,
            code=MDNS_CANARY,
            arguments=[str(MDNS_RESPONDER)],
        )
        tcp_denied = _run_denial_canary(
            sandbox_executable=sandbox_executable,
            profile=profile,
            code=TCP_CANARY,
        )
        unix_allowed = _run_unix_canary(
            sandbox_executable=sandbox_executable,
            target_socket_paths=socket_paths,
        )
        target_status, timed_out = _run_sandboxed(
            sandbox_executable=sandbox_executable,
            profile=profile,
            argv=[executable_path, *safe_argv[1:]],
            timeout_seconds=arguments.timeout_seconds,
        )
        evidence = {
            "schema_version": "1.0.0",
            "evidence_label": EVIDENCE_LABEL,
            "profile": "offline",
            "argv": list(safe_argv),
            "executable": {"path": executable_path, "sha256": executable_hash},
            "sandbox_profile_sha256": profile_hash,
            "start_time": start_time,
            "end_time": _timestamp(),
            "canaries": {
                "external_tcp_denied": tcp_denied,
                "local_unix_socket_allowed": unix_allowed,
                "mdns_responder_socket_denied": mdns_denied,
            },
            "target": {"exit_status": target_status, "timed_out": timed_out},
            "result": "passed" if target_status == 0 and not timed_out else "failed",
        }
        _record_evidence(evidence, stdout)
        return 0 if evidence["result"] == "passed" else 1
    except VerificationError as error:
        evidence = _failure_evidence(start_time=start_time, argv=safe_argv)
        try:
            _record_evidence(evidence, stdout)
        except VerificationError:
            print("zero-egress verification failed: evidence could not be recorded", file=stderr)
            return 1
        print(f"zero-egress verification failed: {error}", file=stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
