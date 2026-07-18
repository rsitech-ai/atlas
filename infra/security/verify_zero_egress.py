from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import re
import select
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


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    pid: int
    start_seconds: int
    start_microseconds: int


class _ProcBSDInfo(ctypes.Structure):
    _fields_ = [
        ("pbi_flags", ctypes.c_uint32),
        ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32),
        ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32),
        ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32),
        ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32),
        ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32),
        ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16),
        ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32),
        ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32),
        ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32),
        ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


_PROC_PIDTBSDINFO = 3
_TRACKING_POLL_SECONDS = 0.001
_SUPERVISOR_GRACE_SECONDS = 0.05
_TARGET_GATE_CODE = (
    "import os,sys; gate=int(sys.argv[1]); "
    "allowed=os.read(gate,1)==b'G'; os.close(gate); "
    "raise SystemExit(125) if not allowed else os.execv(sys.argv[2],sys.argv[2:])"
)
_SUPERVISOR_CODE = (
    "import os,subprocess,sys,time; "
    "control=int(sys.argv[1]); ready=int(sys.argv[2]); target=sys.argv[3:]; "
    "gate_read,gate_write=os.pipe(); "
    "child=subprocess.Popen([sys.executable,'-c'," + repr(_TARGET_GATE_CODE) + ","
    "str(gate_read),*target],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,"
    "stderr=subprocess.DEVNULL,pass_fds=(gate_read,)); "
    "os.close(gate_read); os.write(ready,(str(child.pid)+'\\n').encode('ascii')); "
    "os.close(ready); allowed=os.read(control,1)==b'G'; os.close(control); "
    "os.write(gate_write,b'G' if allowed else b'X'); os.close(gate_write); "
    "status=child.wait(); time.sleep(" + repr(_SUPERVISOR_GRACE_SECONDS) + "); "
    "raise SystemExit(status if status>=0 else 128-status)"
)
PROCESS_CLEANUP_EVIDENCE = {
    "binding": "gated_supervisor_libproc_parentage_and_start_identity_polling",
    "limitation": "not_kernel_event_bound_short_lived_descendant_may_escape_observation",
}


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


def _load_libproc() -> ctypes.CDLL:
    try:
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    except OSError as error:
        raise VerificationError("process tracker unavailable") from error
    library.proc_pidinfo.argtypes = [
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_uint64,
        ctypes.c_void_p,
        ctypes.c_int,
    ]
    library.proc_pidinfo.restype = ctypes.c_int
    library.proc_listchildpids.argtypes = [
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_int,
    ]
    library.proc_listchildpids.restype = ctypes.c_int
    return library


_LIBPROC: ctypes.CDLL | None = None


def _libproc() -> ctypes.CDLL:
    global _LIBPROC
    if _LIBPROC is None:
        _LIBPROC = _load_libproc()
    return _LIBPROC


def _read_process_record(process_id: int) -> tuple[ProcessIdentity, int] | None:
    record = _ProcBSDInfo()
    result = _libproc().proc_pidinfo(
        process_id,
        _PROC_PIDTBSDINFO,
        0,
        ctypes.byref(record),
        ctypes.sizeof(record),
    )
    if result == 0:
        return None
    if result != ctypes.sizeof(record) or record.pbi_pid != process_id:
        raise VerificationError("process tracker inspection failed")
    return (
        ProcessIdentity(
            pid=process_id,
            start_seconds=int(record.pbi_start_tvsec),
            start_microseconds=int(record.pbi_start_tvusec),
        ),
        int(record.pbi_ppid),
    )


def _read_process_identity(process_id: int) -> ProcessIdentity | None:
    record = _read_process_record(process_id)
    return None if record is None else record[0]


def _list_child_pids(process_id: int) -> tuple[int, ...]:
    estimate = _libproc().proc_listchildpids(process_id, None, 0)
    if estimate < 0:
        raise VerificationError("process tracker inspection failed")
    capacity = max(64, estimate + 32)
    while True:
        buffer = (ctypes.c_int * capacity)()
        count = _libproc().proc_listchildpids(
            process_id,
            buffer,
            ctypes.sizeof(buffer),
        )
        if count < 0:
            raise VerificationError("process tracker inspection failed")
        if count < capacity:
            return tuple(int(buffer[index]) for index in range(count) if buffer[index] > 0)
        capacity *= 2
        if capacity > 1_048_576:
            raise VerificationError("process tracker inspection failed")


def _signal_tracked_process(
    expected: ProcessIdentity,
    signal_number: signal.Signals,
) -> bool:
    current = _read_process_identity(expected.pid)
    if current is None:
        return False
    if current != expected:
        raise VerificationError("tracked process identity changed")
    try:
        os.kill(expected.pid, signal_number)
    except ProcessLookupError:
        return False
    except OSError as error:
        raise VerificationError("sandbox child cleanup failed") from error
    return True


class _DarwinProcessTracker:
    """Continuously binds observed descendant PIDs to Darwin start identities."""

    def __init__(self, process_id: int) -> None:
        identity = _read_process_identity(process_id)
        if identity is None:
            raise VerificationError("process tracker unavailable")
        self.root = identity
        self.identities: dict[int, ProcessIdentity] = {process_id: identity}

    def observe(self, process_id: int, *, expected_parent: int) -> ProcessIdentity:
        record = _read_process_record(process_id)
        if record is None or record[1] != expected_parent:
            raise VerificationError("process tracker handshake failed")
        identity = record[0]
        prior = self.identities.get(process_id)
        if prior is not None and prior != identity:
            raise VerificationError("tracked process identity changed")
        self.identities[process_id] = identity
        return identity

    def refresh(self) -> None:
        pending = list(self.identities.values())
        inspected: set[ProcessIdentity] = set()
        while pending:
            expected = pending.pop()
            if expected in inspected:
                continue
            inspected.add(expected)
            current = _read_process_identity(expected.pid)
            if current is None:
                continue
            if current != expected:
                raise VerificationError("tracked process identity changed")
            for child_id in _list_child_pids(expected.pid):
                record = _read_process_record(child_id)
                if record is None or record[1] != expected.pid:
                    continue
                child = record[0]
                prior = self.identities.get(child_id)
                if prior is not None and prior != child:
                    raise VerificationError("tracked process identity changed")
                if prior is None:
                    self.identities[child_id] = child
                    pending.append(child)

    def active(self) -> tuple[ProcessIdentity, ...]:
        active: list[ProcessIdentity] = []
        for expected in self.identities.values():
            current = _read_process_identity(expected.pid)
            if current is None:
                continue
            if current != expected:
                raise VerificationError("tracked process identity changed")
            active.append(expected)
        return tuple(active)


def _cleanup_tracked_processes(
    process: subprocess.Popen[bytes],
    tracker: _DarwinProcessTracker,
) -> None:
    tracker.refresh()
    active = tracker.active()
    for identity in active:
        _signal_tracked_process(identity, signal.SIGTERM)
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        tracker.refresh()
        if not tracker.active():
            break
        time.sleep(0.01)
    for identity in tracker.active():
        _signal_tracked_process(identity, signal.SIGKILL)
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if not tracker.active():
            break
        time.sleep(0.01)
    if tracker.active():
        raise VerificationError("sandbox child cleanup left a surviving descendant")
    try:
        process.wait(timeout=0.2)
    except subprocess.TimeoutExpired as error:
        raise VerificationError("sandbox child cleanup left a surviving descendant") from error
    except OSError as error:
        raise VerificationError("sandbox child cleanup failed") from error


def _cleanup_untracked_root(
    process: subprocess.Popen[bytes],
    identity: ProcessIdentity | None,
) -> None:
    if identity is not None:
        _signal_tracked_process(identity, signal.SIGTERM)
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        if identity is not None:
            _signal_tracked_process(identity, signal.SIGKILL)
        try:
            process.wait(timeout=0.5)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise VerificationError("sandbox child cleanup failed") from error
    except OSError as error:
        raise VerificationError("sandbox child cleanup failed") from error


def _read_supervisor_target(
    descriptor: int,
    process: subprocess.Popen[bytes],
    *,
    deadline: float,
) -> int:
    payload = bytearray()
    while time.monotonic() < deadline and len(payload) <= 32:
        if process.poll() is not None:
            break
        readable, _, _ = select.select([descriptor], [], [], _TRACKING_POLL_SECONDS)
        if not readable:
            continue
        chunk = os.read(descriptor, 32)
        if not chunk:
            break
        payload.extend(chunk)
        if b"\n" in payload:
            break
    try:
        line, remainder = bytes(payload).split(b"\n", 1)
        if remainder or not line.isdigit():
            raise ValueError
        process_id = int(line)
    except ValueError as error:
        raise VerificationError("process tracker handshake failed") from error
    if process_id <= 0:
        raise VerificationError("process tracker handshake failed")
    return process_id


def _run_sandboxed(
    *,
    sandbox_executable: Path,
    profile: str,
    argv: Sequence[str],
    timeout_seconds: float,
) -> tuple[int | None, bool]:
    control_read, control_write = os.pipe()
    ready_read, ready_write = os.pipe()
    process: subprocess.Popen[bytes] | None = None
    root_identity: ProcessIdentity | None = None
    try:
        process = subprocess.Popen(
            [
                str(sandbox_executable),
                "-p",
                profile,
                "--",
                sys.executable,
                "-c",
                _SUPERVISOR_CODE,
                str(control_read),
                str(ready_write),
                *argv,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            pass_fds=(control_read, ready_write),
        )
    except OSError as error:
        os.close(control_read)
        os.close(control_write)
        os.close(ready_read)
        os.close(ready_write)
        raise VerificationError("sandbox child could not start") from error
    os.close(control_read)
    os.close(ready_write)
    try:
        root_identity = _read_process_identity(process.pid)
        tracker = _DarwinProcessTracker(process.pid)
        try:
            target_id = _read_supervisor_target(
                ready_read,
                process,
                deadline=time.monotonic() + min(timeout_seconds, 3),
            )
        except VerificationError as handshake_error:
            rejected_status = process.poll()
            if rejected_status is None:
                try:
                    rejected_status = process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    raise handshake_error from None
            _cleanup_tracked_processes(process, tracker)
            return rejected_status, False
        tracker.observe(target_id, expected_parent=process.pid)
        os.write(control_write, b"G")
        deadline = time.monotonic() + timeout_seconds
        status: int | None = None
        timed_out = False
        while True:
            tracker.refresh()
            status = process.poll()
            if status is not None:
                tracker.refresh()
                break
            if time.monotonic() >= deadline:
                status = None
                timed_out = True
                break
            time.sleep(_TRACKING_POLL_SECONDS)
        _cleanup_tracked_processes(process, tracker)
        return status, timed_out
    except VerificationError:
        with suppress(OSError):
            os.close(control_write)
        if "tracker" in locals():
            _cleanup_tracked_processes(process, tracker)
        else:
            _cleanup_untracked_root(process, root_identity)
        raise
    except OSError as error:
        with suppress(OSError):
            os.close(control_write)
        if "tracker" in locals():
            _cleanup_tracked_processes(process, tracker)
        else:
            _cleanup_untracked_root(process, root_identity)
        raise VerificationError("sandbox child wait failed") from error
    finally:
        with suppress(OSError):
            os.close(control_write)
        with suppress(OSError):
            os.close(ready_read)


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
        "process_cleanup": PROCESS_CLEANUP_EVIDENCE,
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
            "process_cleanup": PROCESS_CLEANUP_EVIDENCE,
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
