"""Fail-closed shell release workflow contracts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_runtime_builder_cli_is_pinned_and_refuses_to_claim_closure() -> None:
    script = (ROOT / "script" / "build_release_runtime.py").read_text(encoding="utf-8")

    assert "RuntimeBuildInputs.local" in script
    assert "build_runtime_payload" in script
    assert 'print("runtime_dependency_closure_verified=false")' in script
    assert "allow-dirty" not in script


def test_package_release_assembles_before_release_gate() -> None:
    script = (ROOT / "script" / "package_release.sh").read_text(encoding="utf-8")

    assembly = script.index("assemble_release_app.py")
    release_gate = script.index("release_check.py --require-release")
    assert assembly < release_gate
    assert "git rev-list --count HEAD" in script


def test_runtime_preflight_cli_fails_closed_for_native_shell(tmp_path: Path) -> None:
    bundle = tmp_path / "RSIAtlas.app"
    executable = bundle / "Contents" / "MacOS" / "RSIAtlas"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"native-shell")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "script" / "check_release_runtime.py"),
            "--bundle",
            str(bundle),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "embedded_python_missing" in result.stdout
    assert "runtime_ready_for_signing=false" in result.stdout
    assert "runtime_dependency_closure_unverified" in result.stdout


def test_signing_script_is_inside_out_and_archives_after_stapling() -> None:
    script = (ROOT / "script" / "sign_and_notarize.sh").read_text(encoding="utf-8")

    runtime_preflight = script.index("check_release_runtime.py")
    first_codesign = script.index("codesign ")
    staple = script.index("stapler staple")
    final_archive = script.index("FINAL_ARCHIVE=")
    assert runtime_preflight < first_codesign
    assert staple < final_archive
    assert "codesign --force --deep" not in script
    assert "--options runtime" in script
    assert "--timestamp" in script
    assert "stapler validate" in script
    assert "shasum -a 256" in script
