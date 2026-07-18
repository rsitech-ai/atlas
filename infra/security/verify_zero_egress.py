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
import time
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class ExecutableIdentity:
    path: str
    descriptor: int
    sha256: str
    device: int
    inode: int


@dataclass(frozen=True, slots=True)
class UnixSocketIdentity:
    path: str
    device: int
    inode: int
    parent_device: int
    parent_inode: int


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_descriptor(descriptor: int) -> str:
    digest = hashlib.sha256()
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        os.lseek(descriptor, 0, os.SEEK_SET)
    except OSError as error:
        raise VerificationError("executable identity could not be recorded") from error
    return digest.hexdigest()


def _open_executable_identity(argv: Sequence[str]) -> ExecutableIdentity:
    executable = argv[0]
    candidate = executable if os.path.isabs(executable) else shutil.which(executable)
    if candidate is None:
        raise VerificationError("target executable is unavailable")
    try:
        path = Path(candidate).resolve(strict=True)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or not os.access(path, os.X_OK):
            raise VerificationError("target executable is invalid")
        identity = ExecutableIdentity(
            path=str(path),
            descriptor=descriptor,
            sha256=_sha256_descriptor(descriptor),
            device=metadata.st_dev,
            inode=metadata.st_ino,
        )
        _validate_executable_identity(identity)
        return identity
    except VerificationError:
        if "descriptor" in locals():
            os.close(descriptor)
        raise
    except OSError as error:
        if "descriptor" in locals():
            os.close(descriptor)
        raise VerificationError("target executable is invalid") from error


def _validate_executable_identity(identity: ExecutableIdentity) -> None:
    try:
        descriptor_metadata = os.fstat(identity.descriptor)
        path_metadata = os.stat(identity.path, follow_symlinks=False)
    except OSError as error:
        raise VerificationError("executable path identity changed") from error
    expected = (identity.device, identity.inode)
    if (
        not stat.S_ISREG(path_metadata.st_mode)
        or (descriptor_metadata.st_dev, descriptor_metadata.st_ino) != expected
        or (path_metadata.st_dev, path_metadata.st_ino) != expected
    ):
        raise VerificationError("executable path identity changed")


def _executable_evidence(identity: ExecutableIdentity | None) -> dict[str, object]:
    if identity is None:
        return {
            "path": None,
            "sha256": None,
            "device": None,
            "inode": None,
            "execution_binding": "unavailable",
            "limitation": "path_execution_not_kernel_bound",
        }
    return {
        "path": identity.path,
        "sha256": identity.sha256,
        "device": identity.device,
        "inode": identity.inode,
        "execution_binding": "opened_descriptor_hash_with_path_revalidation",
        "limitation": "path_execution_not_kernel_bound",
    }


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


def _argv_fingerprint(argv: Sequence[str]) -> dict[str, object]:
    canonical = json.dumps(list(argv), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {"count": len(argv), "sha256": hashlib.sha256(canonical).hexdigest()}


def _capture_socket_identity(path: str) -> UnixSocketIdentity:
    candidate = Path(path)
    try:
        decision = NetworkPolicy.offline(unix_socket_paths=[candidate]).authorize(
            role=ProcessRole.ENGINE,
            unix_socket_path=candidate,
        )
        metadata = os.stat(candidate, follow_symlinks=False)
        parent_metadata = os.stat(candidate.parent, follow_symlinks=False)
    except (OSError, ValueError) as error:
        raise VerificationError("Unix socket allowance failed validation") from error
    if not decision.allowed or decision.canonical_destination is None:
        raise VerificationError("Unix socket allowance failed validation")
    return UnixSocketIdentity(
        path=decision.canonical_destination,
        device=metadata.st_dev,
        inode=metadata.st_ino,
        parent_device=parent_metadata.st_dev,
        parent_inode=parent_metadata.st_ino,
    )


def _safe_socket_paths(paths: Sequence[str]) -> tuple[UnixSocketIdentity, ...]:
    if len(paths) != len(set(paths)):
        raise VerificationError("duplicate Unix socket allowance")
    validated: list[UnixSocketIdentity] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not SAFE_PROFILE_PATH.fullmatch(raw_path):
            raise VerificationError("Unix socket allowance is not profile-safe")
        validated.append(_capture_socket_identity(str(path)))
    return tuple(sorted(validated, key=lambda identity: identity.path))


def _revalidate_socket_identities(identities: Sequence[UnixSocketIdentity]) -> None:
    for expected in identities:
        try:
            current = _capture_socket_identity(expected.path)
        except VerificationError as error:
            raise VerificationError("Unix socket identity changed") from error
        if current != expected:
            raise VerificationError("Unix socket identity changed")


def _sandbox_profile(socket_paths: Sequence[str]) -> str:
    rules = ["(version 1)", "(allow default)", "(deny network*)"]
    for path in socket_paths:
        if not SAFE_PROFILE_PATH.fullmatch(path):
            raise VerificationError("Unix socket allowance is not profile-safe")
        rules.append(f'(allow network-outbound (literal "{path}"))')
    return "\n".join(rules) + "\n"


def _descendant_processes(root_pid: int) -> set[int]:
    try:
        result = subprocess.run(
            ["/bin/ps", "-axo", "pid=,ppid="],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise VerificationError("sandbox child cleanup inspection failed") from error
    children: dict[int, set[int]] = {}
    try:
        for line in result.stdout.splitlines():
            pid_text, parent_text = line.split()
            children.setdefault(int(parent_text), set()).add(int(pid_text))
    except (TypeError, ValueError) as error:
        raise VerificationError("sandbox child cleanup inspection failed") from error
    descendants: set[int] = set()
    pending = [root_pid]
    while pending:
        parent = pending.pop()
        for child in children.get(parent, set()):
            if child not in descendants:
                descendants.add(child)
                pending.append(child)
    return descendants


def _process_is_active(process_id: int) -> bool:
    try:
        result = subprocess.run(
            ["/bin/ps", "-p", str(process_id), "-o", "stat="],
            check=False,
            capture_output=True,
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise VerificationError("sandbox child cleanup inspection failed") from error
    state = result.stdout.strip()
    return result.returncode == 0 and bool(state) and not state.startswith("Z")


def _signal_process(process_id: int, signal_number: signal.Signals) -> None:
    try:
        os.kill(process_id, signal_number)
    except ProcessLookupError:
        return
    except OSError as error:
        raise VerificationError("sandbox child cleanup failed") from error


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    descendants = _descendant_processes(process.pid)
    for process_id in descendants:
        _signal_process(process_id, signal.SIGTERM)
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError as error:
        raise VerificationError("sandbox child cleanup failed") from error
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        pass
    except OSError as error:
        raise VerificationError("sandbox child cleanup failed") from error
    for process_id in descendants:
        if _process_is_active(process_id):
            _signal_process(process_id, signal.SIGKILL)
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as error:
            raise VerificationError("sandbox child cleanup failed") from error
        try:
            process.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise VerificationError("sandbox child cleanup failed") from error
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline and any(
        _process_is_active(process_id) for process_id in descendants
    ):
        time.sleep(0.02)
    if any(_process_is_active(process_id) for process_id in descendants):
        raise VerificationError("sandbox child cleanup left a surviving descendant")


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
        "argv_fingerprint": _argv_fingerprint(argv),
        "executable": _executable_evidence(None),
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
    executable_identity: ExecutableIdentity | None = None
    try:
        arguments = _parser().parse_args(argv)
        if not 0.1 <= arguments.timeout_seconds <= 60:
            raise VerificationError("target timeout is invalid")
        safe_argv = _command_from_arguments(arguments)
        if not sandbox_executable.is_file() or not os.access(sandbox_executable, os.X_OK):
            raise VerificationError("sandbox support unavailable")
        socket_identities = _safe_socket_paths(arguments.allow_unix_socket)
        socket_paths = tuple(identity.path for identity in socket_identities)
        profile = _sandbox_profile(socket_paths)
        profile_hash = hashlib.sha256(profile.encode("utf-8")).hexdigest()
        executable_identity = _open_executable_identity(safe_argv)
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
        _revalidate_socket_identities(socket_identities)
        _validate_executable_identity(executable_identity)
        target_status, timed_out = _run_sandboxed(
            sandbox_executable=sandbox_executable,
            profile=profile,
            argv=[executable_identity.path, *safe_argv[1:]],
            timeout_seconds=arguments.timeout_seconds,
        )
        _validate_executable_identity(executable_identity)
        _revalidate_socket_identities(socket_identities)
        evidence = {
            "schema_version": "1.0.0",
            "evidence_label": EVIDENCE_LABEL,
            "profile": "offline",
            "argv_fingerprint": _argv_fingerprint(safe_argv),
            "executable": _executable_evidence(executable_identity),
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
    finally:
        if executable_identity is not None:
            with suppress(OSError):
                os.close(executable_identity.descriptor)


if __name__ == "__main__":
    raise SystemExit(main())
