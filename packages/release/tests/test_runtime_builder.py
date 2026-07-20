from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from rsi_atlas_release.runtime_builder import _copy_distinct_file, compile_engine_launcher

ROOT = Path(__file__).resolve().parents[3]


def test_native_launcher_uses_only_in_bundle_isolated_python(tmp_path: Path) -> None:
    bundle = tmp_path / "RSIAtlas.app"
    launcher = bundle / "Contents" / "MacOS" / "RSIAtlasEngine"
    python = bundle / "Contents" / "Resources" / "runtime" / "python" / "bin" / "python3"
    capture = tmp_path / "argv.txt"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > " + repr(str(capture)) + "\n",
        encoding="utf-8",
    )
    python.chmod(0o700)

    compile_engine_launcher(
        source=ROOT / "infra" / "release" / "RSIAtlasEngine.c",
        destination=launcher,
    )
    result = subprocess.run(
        [str(launcher), "doctor", "--json"],
        cwd=Path("/tmp"),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert capture.read_text(encoding="utf-8").splitlines() == [
        "-I",
        "-s",
        "-m",
        "rsi_atlas_engine",
        "doctor",
        "--json",
    ]


def test_native_launcher_fails_closed_when_embedded_python_is_missing(tmp_path: Path) -> None:
    launcher = tmp_path / "RSIAtlas.app" / "Contents" / "MacOS" / "RSIAtlasEngine"
    compile_engine_launcher(
        source=ROOT / "infra" / "release" / "RSIAtlasEngine.c",
        destination=launcher,
    )

    result = subprocess.run(
        [str(launcher), "--help"],
        cwd=Path("/tmp"),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 126
    assert result.stdout == ""
    assert result.stderr == "RSIAtlasEngine: embedded Python launch failed\n"
    assert str(tmp_path) not in result.stderr


def test_native_provider_copy_rejects_same_destination_with_different_content(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first" / "libsame.dylib"
    second = tmp_path / "second" / "libsame.dylib"
    destination = tmp_path / "runtime" / "libsame.dylib"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"provider-a")
    second.write_bytes(b"provider-b")

    _copy_distinct_file(first, destination)
    with pytest.raises(ValueError, match="destination collision"):
        _copy_distinct_file(second, destination)
