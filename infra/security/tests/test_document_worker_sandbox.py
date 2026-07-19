"""OS-enforced Seatbelt canaries for the document-worker profile."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from rsi_atlas_ingestion.worker_runner import (
    DocumentWorkerRunnerError,
    render_document_worker_profile,
)

SANDBOX_EXECUTABLE = Path("/usr/bin/sandbox-exec")


def _run_canary(profile_text: Path, code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SANDBOX_EXECUTABLE), "-f", str(profile_text), sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


@pytest.fixture
def sandboxed_profile(tmp_path: Path) -> Path:
    if not SANDBOX_EXECUTABLE.is_file():
        pytest.skip("sandbox-exec unavailable")
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"canary")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    profile = render_document_worker_profile(
        python_executable=Path(sys.executable),
        artifact_path=artifact,
        run_directory=run_dir,
    )
    path = run_dir / "profile.sb"
    path.write_text(profile, encoding="utf-8")
    return path


def test_sandbox_profile_denies_external_tcp(sandboxed_profile: Path) -> None:
    code = (
        "import socket; s=socket.socket(); s.settimeout(1); "
        "s.connect(('1.1.1.1', 443)); print('connected')"
    )
    result = _run_canary(sandboxed_profile, code)
    assert result.returncode != 0
    assert "connected" not in result.stdout


def test_sandbox_profile_denies_dns_udp(sandboxed_profile: Path) -> None:
    result = _run_canary(
        sandboxed_profile,
        "import socket; socket.getaddrinfo('example.com', 80); print('resolved')",
    )
    assert result.returncode != 0
    assert "resolved" not in result.stdout


def test_sandbox_profile_denies_arbitrary_user_file_read(
    sandboxed_profile: Path, tmp_path: Path
) -> None:
    secret = Path.home() / ".rsi-atlas-document-worker-canary-secret"
    try:
        secret.write_text("secret", encoding="utf-8")
        result = _run_canary(
            sandboxed_profile,
            f"print(open({str(secret)!r}).read())",
        )
        assert result.returncode != 0
        assert "secret" not in result.stdout
    finally:
        secret.unlink(missing_ok=True)


def test_sandbox_profile_denies_write_outside_run_directory(
    sandboxed_profile: Path, tmp_path: Path
) -> None:
    outside = tmp_path / "outside.txt"
    result = _run_canary(
        sandboxed_profile,
        f"open({str(outside)!r}, 'w').write('nope'); print('wrote')",
    )
    assert result.returncode != 0
    assert "wrote" not in result.stdout
    assert not outside.exists()


def test_sandbox_profile_denies_fork_and_exec(sandboxed_profile: Path) -> None:
    result = _run_canary(
        sandboxed_profile,
        "import os; os.fork(); print('forked')",
    )
    assert result.returncode != 0
    assert "forked" not in result.stdout

    result = _run_canary(
        sandboxed_profile,
        "import os; os.execv('/bin/echo', ['echo', 'escaped']); print('execed')",
    )
    assert result.returncode != 0
    assert "escaped" not in result.stdout
    assert "execed" not in result.stdout


def test_sandbox_profile_denies_keychain_mach_lookup(sandboxed_profile: Path) -> None:
    """Prove Seatbelt denies Keychain Mach services named in document-worker.sb."""
    code = r"""
import ctypes
from ctypes import POINTER, c_char_p, c_int, c_uint32, byref

mach_port_t = c_uint32
kern_return_t = c_int
lib = ctypes.CDLL(None)
bootstrap_port = mach_port_t.in_dll(lib, "bootstrap_port")
bootstrap_look_up = lib.bootstrap_look_up
bootstrap_look_up.restype = kern_return_t
bootstrap_look_up.argtypes = [mach_port_t, c_char_p, POINTER(mach_port_t)]

denied = (
    b"com.apple.securityd",
    b"com.apple.SecurityServer",
    b"com.apple.keychain.xpc",
)
for name in denied:
    port = mach_port_t(0)
    kr = bootstrap_look_up(bootstrap_port, name, byref(port))
    if kr == 0 or port.value != 0:
        print("keychain-allowed", name.decode(), kr, port.value)
        raise SystemExit(0)

# Control: a non-Keychain com.apple.* lookup still succeeds under the allow regex.
allowed_port = mach_port_t(0)
allowed_kr = bootstrap_look_up(
    bootstrap_port, b"com.apple.system.logger", byref(allowed_port)
)
if allowed_kr != 0 or allowed_port.value == 0:
    print("control-failed", allowed_kr, allowed_port.value)
    raise SystemExit(2)
print("keychain-denied")
raise SystemExit(1)
"""
    result = _run_canary(sandboxed_profile, code)
    assert result.returncode != 0
    assert "keychain-denied" in result.stdout
    assert "keychain-allowed" not in result.stdout


def test_render_fails_closed_when_template_missing(tmp_path: Path) -> None:
    with pytest.raises(DocumentWorkerRunnerError) as raised:
        render_document_worker_profile(
            python_executable=Path(sys.executable),
            artifact_path=tmp_path / "a.bin",
            run_directory=tmp_path,
            template_path=tmp_path / "missing.sb",
        )
    assert raised.value.code in {"sandbox_profile_missing", "sandbox_profile_unresolved"}
