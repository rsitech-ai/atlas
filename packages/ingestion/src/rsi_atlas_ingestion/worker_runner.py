"""Bounded, Seatbelt-enforced launcher for the isolated document worker."""

from __future__ import annotations

import hashlib
import os
import selectors
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from rsi_atlas_document_worker.protocol import (
    DocumentWorkerRequest,
    DocumentWorkerResponse,
    WorkerOperation,
    WorkerResponseStatus,
    decode_response,
    encode_request,
)

SANDBOX_EXECUTABLE = Path("/usr/bin/sandbox-exec")
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_STDOUT_BYTES = 256 * 1024
DEFAULT_MAX_STDERR_BYTES = 64 * 1024
_FD_LOCK = threading.Lock()
_SENSITIVE_ENV_MARKERS = (
    "AWS_",
    "AZURE_",
    "DOCKER_",
    "GITHUB_",
    "GOOGLE_",
    "OPENAI_",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "CREDENTIAL",
    "DATABASE_URL",
    "RSI_ATLAS_",
)


class DocumentWorkerRunnerError(RuntimeError):
    """Sanitized failure launching or supervising the document worker."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class DocumentWorkerRunResult:
    response: DocumentWorkerResponse
    run_directory: Path
    exit_code: int
    duration_seconds: float
    stdout_bytes: int
    stderr_bytes: int


def profile_template_path() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "infra" / "security" / "document-worker.sb"
        if candidate.is_file():
            return candidate
    raise DocumentWorkerRunnerError("sandbox_profile_missing")


def _scrub_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    source = dict(os.environ if base is None else base)
    cleaned: dict[str, str] = {}
    for key, value in source.items():
        upper = key.upper()
        if any(marker in upper for marker in _SENSITIVE_ENV_MARKERS):
            continue
        if key.startswith("PG") or key in {
            "DYLD_INSERT_LIBRARIES",
            "DYLD_LIBRARY_PATH",
            "LD_PRELOAD",
            "PYTHONSTARTUP",
        }:
            continue
        cleaned[key] = value
    required = (
        "PATH",
        "HOME",
        "TMPDIR",
        "TMP",
        "TEMP",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "UV_PROJECT_ENVIRONMENT",
    )
    return {key: cleaned[key] for key in required if key in cleaned}


def _literal_rule(path: Path) -> str:
    text = str(path)
    if '"' in text or "\n" in text:
        raise DocumentWorkerRunnerError("sandbox_profile_path_invalid")
    return f'(literal "{text}")'


def _subpath_rule(path: Path) -> str:
    text = str(path)
    if '"' in text or "\n" in text:
        raise DocumentWorkerRunnerError("sandbox_profile_path_invalid")
    return f'(subpath "{text}")'


def render_document_worker_profile(
    *,
    python_executable: Path,
    artifact_path: Path,
    run_directory: Path,
    template_path: Path | None = None,
) -> str:
    path = template_path or profile_template_path()
    if not path.is_file():
        raise DocumentWorkerRunnerError("sandbox_profile_missing")
    template = path.read_text(encoding="utf-8")
    python_executable = Path(python_executable)
    home = Path.home().resolve()
    home_allows: set[Path] = {
        (home / ".local").resolve(),
        Path(sys.prefix).resolve(),
        Path(sys.base_prefix).resolve(),
    }
    for parent in Path(__file__).resolve().parents:
        packages = parent / "packages"
        if packages.is_dir():
            home_allows.add(packages.resolve())
            home_allows.add(parent.resolve())
            break
    exec_literals: set[str] = set()
    invoked = python_executable if python_executable.is_absolute() else python_executable.resolve()
    exec_literals.add(str(invoked))
    exec_literals.add(str(invoked.resolve()))
    current = invoked
    for _ in range(4):
        if not current.is_symlink():
            break
        target = Path(os.readlink(current))
        current = target if target.is_absolute() else (current.parent / target)
        exec_literals.add(str(current))
        exec_literals.add(str(current.resolve()))
    for literal in exec_literals:
        home_allows.add(Path(literal).parent.resolve())
    if str(Path(sys.base_prefix).resolve()).startswith(str(home)):
        home_allows.add(Path(sys.base_prefix).resolve())
    home_allow_rules = "\n  ".join(
        _subpath_rule(path) for path in sorted(home_allows, key=lambda item: str(item))
    )
    exec_rules = "\n  ".join(
        f'(literal "{literal}")'
        for literal in sorted(exec_literals)
        if '"' not in literal and "\n" not in literal
    )
    if not exec_rules:
        raise DocumentWorkerRunnerError("sandbox_profile_path_invalid")
    rendered = (
        template.replace("__PYTHON_EXEC_RULES__", exec_rules)
        .replace("__HOME_ALLOW_RULES__", home_allow_rules)
        .replace("__ARTIFACT_READ_RULES__", _literal_rule(artifact_path.resolve()))
        .replace("__USER_HOME__", str(home))
        .replace("__RUN_DIRECTORY__", str(run_directory.resolve()))
    )
    if any(
        token in rendered
        for token in (
            "__PYTHON_EXEC_RULES__",
            "__HOME_ALLOW_RULES__",
            "__ARTIFACT_READ_RULES__",
            "__USER_HOME__",
            "__RUN_DIRECTORY__",
        )
    ):
        raise DocumentWorkerRunnerError("sandbox_profile_unresolved")
    return rendered


def _drain_process_output(
    process: subprocess.Popen[bytes],
    *,
    stdout_fd: int,
    stderr_fd: int,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
    deadline: float,
) -> tuple[bytes, bytes]:
    """Drain both child pipes while it runs, enforcing strict memory bounds."""
    selector = selectors.DefaultSelector()
    buffers = {
        stdout_fd: bytearray(),
        stderr_fd: bytearray(),
    }
    limits = {
        stdout_fd: max_stdout_bytes,
        stderr_fd: max_stderr_bytes,
    }
    try:
        for descriptor in buffers:
            os.set_blocking(descriptor, False)
            selector.register(descriptor, selectors.EVENT_READ)

        while process.poll() is None or selector.get_map():
            if time.monotonic() > deadline:
                raise DocumentWorkerRunnerError("worker_timeout")
            if not selector.get_map():
                time.sleep(0.01)
                continue
            for key, _ in selector.select(timeout=0.01):
                descriptor = int(key.fd)
                buffer = buffers[descriptor]
                limit = limits[descriptor]
                try:
                    chunk = os.read(descriptor, min(65_536, max(1, limit - len(buffer) + 1)))
                except BlockingIOError:
                    continue
                except OSError as error:
                    raise DocumentWorkerRunnerError("worker_io_failed") from error
                if not chunk:
                    selector.unregister(descriptor)
                    continue
                buffer.extend(chunk)
                if len(buffer) > limit:
                    raise DocumentWorkerRunnerError("worker_output_too_large")
    finally:
        selector.close()
    return bytes(buffers[stdout_fd]), bytes(buffers[stderr_fd])


def _close_quietly(*descriptors: int) -> None:
    for descriptor in descriptors:
        if descriptor < 0:
            continue
        with suppress(OSError):
            os.close(descriptor)


def _reserve_fd(target: int, source: int) -> int:
    if source == target:
        os.set_inheritable(source, True)
        return source
    os.dup2(source, target, inheritable=True)
    os.close(source)
    return target


def _dup_existing(fd: int) -> int | None:
    try:
        return os.dup(fd)
    except OSError:
        return None


def _restore_fd(target: int, saved: int | None) -> None:
    if saved is None:
        with suppress(OSError):
            os.close(target)
        return
    os.dup2(saved, target)
    os.close(saved)


class DocumentWorkerRunner:
    """Launch one sandboxed worker against one read-only artifact and run directory."""

    def __init__(
        self,
        *,
        python_executable: Path | None = None,
        profile_template: Path | None = None,
        sandbox_executable: Path = SANDBOX_EXECUTABLE,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_stdout_bytes: int = DEFAULT_MAX_STDOUT_BYTES,
        max_stderr_bytes: int = DEFAULT_MAX_STDERR_BYTES,
    ) -> None:
        # Keep the venv wrapper path for module discovery; Seatbelt also allows the real binary.
        self.python_executable = Path(python_executable or sys.executable)
        if not self.python_executable.is_file():
            raise DocumentWorkerRunnerError("python_executable_missing")
        self.profile_template = profile_template
        self.sandbox_executable = sandbox_executable
        self.timeout_seconds = timeout_seconds
        self.max_stdout_bytes = max_stdout_bytes
        self.max_stderr_bytes = max_stderr_bytes

    def run_echo_hash(
        self,
        *,
        artifact_path: Path,
        run_directory: Path,
        run_id: str,
        max_output_bytes: int = 1_048_576,
    ) -> DocumentWorkerRunResult:
        artifact = artifact_path
        if artifact.is_symlink():
            raise DocumentWorkerRunnerError("artifact_symlink_rejected")
        artifact = artifact.resolve()
        if not artifact.is_file():
            raise DocumentWorkerRunnerError("artifact_missing")
        run_dir = run_directory.resolve()
        run_dir.mkdir(parents=True, exist_ok=False)
        os.chmod(run_dir, 0o700)

        payload = artifact.read_bytes()
        request = DocumentWorkerRequest(
            operation=WorkerOperation.ECHO_HASH,
            run_id=run_id,
            artifact_sha256=hashlib.sha256(payload).hexdigest(),
            artifact_size_bytes=len(payload),
            max_output_bytes=max_output_bytes,
        )
        return self.run_request(request=request, artifact_path=artifact, run_directory=run_dir)

    def run_request(
        self,
        *,
        request: DocumentWorkerRequest,
        artifact_path: Path,
        run_directory: Path,
    ) -> DocumentWorkerRunResult:
        if not self.sandbox_executable.is_file():
            raise DocumentWorkerRunnerError("sandbox_unavailable")
        artifact = artifact_path.resolve()
        run_dir = run_directory.resolve()
        if not run_dir.is_dir():
            raise DocumentWorkerRunnerError("run_directory_missing")

        profile_text = render_document_worker_profile(
            python_executable=self.python_executable,
            artifact_path=artifact,
            run_directory=run_dir,
            template_path=self.profile_template,
        )
        profile_path = run_dir / "document-worker.rendered.sb"
        profile_path.write_text(profile_text, encoding="utf-8")
        os.chmod(profile_path, 0o600)

        # Serialize reserved FD 3/4 for the full child lifetime in one engine process.
        # ponytail: global lock; ceiling is one in-process worker at a time. Upgrade: pass
        # dynamic FDs in the protocol instead of fixed 3/4.
        with _FD_LOCK:
            # Save/restore 3/4 so Seatbelt staging cannot clobber unrelated descriptors.
            saved_3 = _dup_existing(3)
            saved_4 = _dup_existing(4)
            opened_artifact = os.open(artifact, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
            opened_run = os.open(
                run_dir, os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
            )
            artifact_fd = run_dir_fd = -1
            stdout_r = stdout_w = stderr_r = stderr_w = -1
            process: subprocess.Popen[bytes] | None = None
            started = time.monotonic()
            try:
                artifact_fd = _reserve_fd(3, opened_artifact)
                opened_artifact = -1
                run_dir_fd = _reserve_fd(4, opened_run)
                opened_run = -1
                stdout_r, stdout_w = os.pipe()
                stderr_r, stderr_w = os.pipe()
                os.set_inheritable(stdout_w, True)
                os.set_inheritable(stderr_w, True)
                command = [
                    str(self.sandbox_executable),
                    "-f",
                    str(profile_path),
                    str(self.python_executable),
                    "-m",
                    "rsi_atlas_document_worker.worker",
                ]
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=stdout_w,
                    stderr=stderr_w,
                    pass_fds=(3, 4),
                    cwd=str(run_dir),
                    env=_scrub_environment(),
                    start_new_session=True,
                    close_fds=True,
                )
                assert process.stdin is not None
                _close_quietly(stdout_w, stderr_w, 3, 4)
                stdout_w = stderr_w = artifact_fd = run_dir_fd = -1
                try:
                    process.stdin.write(encode_request(request))
                    process.stdin.close()
                except BrokenPipeError as error:
                    raise DocumentWorkerRunnerError("worker_stdin_failed") from error

                stdout, stderr = _drain_process_output(
                    process,
                    stdout_fd=stdout_r,
                    stderr_fd=stderr_r,
                    max_stdout_bytes=self.max_stdout_bytes,
                    max_stderr_bytes=self.max_stderr_bytes,
                    deadline=started + self.timeout_seconds,
                )
                duration = time.monotonic() - started
                exit_code = int(process.returncode)
            except DocumentWorkerRunnerError:
                if process is not None:
                    self._kill_process_group(process)
                self._cleanup_partial_outputs(run_dir)
                raise
            except Exception:
                _close_quietly(
                    stdout_r,
                    stderr_r,
                    stdout_w,
                    stderr_w,
                    artifact_fd,
                    run_dir_fd,
                    opened_artifact,
                    opened_run,
                )
                raise
            finally:
                _close_quietly(
                    stdout_r,
                    stderr_r,
                    stdout_w,
                    stderr_w,
                    artifact_fd,
                    run_dir_fd,
                    opened_artifact,
                    opened_run,
                )
                _restore_fd(3, saved_3)
                _restore_fd(4, saved_4)

        if stderr:
            raise DocumentWorkerRunnerError("worker_stderr_nonempty")

        try:
            response = decode_response(stdout)
        except Exception as error:
            raise DocumentWorkerRunnerError("worker_invalid_response") from error

        if response.run_id != request.run_id:
            raise DocumentWorkerRunnerError("worker_response_identity_mismatch")
        if response.status is WorkerResponseStatus.SUCCEEDED and exit_code != 0:
            raise DocumentWorkerRunnerError("worker_exit_status_mismatch")
        self._validate_output_files(run_dir, response)
        return DocumentWorkerRunResult(
            response=response,
            run_directory=run_dir,
            exit_code=exit_code,
            duration_seconds=duration,
            stdout_bytes=len(stdout),
            stderr_bytes=0,
        )

    @staticmethod
    def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGTERM)
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                break
            except PermissionError:
                pass
            time.sleep(0.01)
        else:
            with suppress(ProcessLookupError, PermissionError):
                os.killpg(process.pid, signal.SIGKILL)
        with suppress(subprocess.TimeoutExpired):
            process.wait(timeout=1)

    @staticmethod
    def _cleanup_partial_outputs(run_directory: Path) -> None:
        for path in run_directory.iterdir():
            if path.name.endswith(".rendered.sb"):
                continue
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)

    @staticmethod
    def _validate_output_files(run_directory: Path, response: DocumentWorkerResponse) -> None:
        allowed = set(response.output_files)
        resolved_root = run_directory.resolve()
        for name in response.output_files:
            path = run_directory / name
            if path.is_symlink():
                raise DocumentWorkerRunnerError("worker_symlink_output")
            if not path.is_file():
                raise DocumentWorkerRunnerError("worker_missing_output")
            if path.resolve().parent != resolved_root:
                raise DocumentWorkerRunnerError("worker_path_traversal")
        for path in run_directory.iterdir():
            if path.name.endswith(".rendered.sb"):
                continue
            if path.is_file() and path.name not in allowed:
                raise DocumentWorkerRunnerError("worker_unexpected_output")
