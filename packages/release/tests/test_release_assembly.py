"""Versioned macOS release-shell assembly tests."""

from __future__ import annotations

import json
import plistlib
import subprocess
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from rsi_atlas_release import assemble_release_app

NOW = datetime(2026, 7, 20, 21, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[3]


def _repo_fixture(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "LICENSE").write_bytes((ROOT / "LICENSE").read_bytes())
    (path / "NOTICE").write_bytes((ROOT / "NOTICE").read_bytes())
    (path / "uv.lock").write_bytes((ROOT / "uv.lock").read_bytes())
    return path


def test_assemble_release_app_writes_versioned_honest_bundle(tmp_path: Path) -> None:
    repo_root = _repo_fixture(tmp_path / "repo")
    source = tmp_path / "RSIAtlas"
    source.write_bytes(b"release-swift-binary")
    source.chmod(0o700)
    destination = tmp_path / "dist" / "RSIAtlas.app"

    result = assemble_release_app(
        source_executable=source,
        destination_bundle=destination,
        version="0.1.0",
        build_number="1",
        repo_root=repo_root,
        created_at=NOW,
    )

    assert result == destination
    plist = plistlib.loads((destination / "Contents" / "Info.plist").read_bytes())
    assert plist["CFBundleIdentifier"] == "ai.rsitech.RSIAtlas"
    assert plist["CFBundleShortVersionString"] == "0.1.0"
    assert plist["CFBundleVersion"] == "1"
    executable = destination / "Contents" / "MacOS" / "RSIAtlas"
    assert executable.read_bytes() == source.read_bytes()
    assert executable.stat().st_mode & 0o111
    resources = destination / "Contents" / "Resources"
    assert (resources / "Legal" / "LICENSE").read_bytes() == (repo_root / "LICENSE").read_bytes()
    assert (resources / "Legal" / "NOTICE").read_bytes() == (repo_root / "NOTICE").read_bytes()
    assert (resources / "sbom.cdx.json").is_file()
    manifest = json.loads((resources / "release-assembly.json").read_text(encoding="utf-8"))
    assert manifest == {
        "blockers": [
            "embedded_python_missing",
            "engine_launcher_missing",
            "postgresql_missing",
            "pgvector_missing",
        ],
        "build_number": "1",
        "bundle_identifier": "ai.rsitech.RSIAtlas",
        "executable_sha256": sha256(source.read_bytes()).hexdigest(),
        "honesty_label": "incomplete_runtime",
        "runtime_complete": False,
        "schema_version": "rsi-atlas.release-assembly.v1",
        "version": "0.1.0",
    }


def test_assemble_release_app_is_deterministic_for_fixed_inputs(tmp_path: Path) -> None:
    repo_root = _repo_fixture(tmp_path / "repo")
    source = tmp_path / "RSIAtlas"
    source.write_bytes(b"release-swift-binary")
    first = tmp_path / "first" / "RSIAtlas.app"
    second = tmp_path / "second" / "RSIAtlas.app"

    for destination in (first, second):
        assemble_release_app(
            source_executable=source,
            destination_bundle=destination,
            version="0.1.0",
            build_number="7",
            repo_root=repo_root,
            created_at=NOW,
        )

    for relative_path in (
        Path("Contents/Info.plist"),
        Path("Contents/Resources/release-assembly.json"),
        Path("Contents/Resources/sbom.cdx.json"),
    ):
        assert (first / relative_path).read_bytes() == (second / relative_path).read_bytes()


def test_assemble_release_app_rejects_unsafe_destination_without_mutation(
    tmp_path: Path,
) -> None:
    repo_root = _repo_fixture(tmp_path / "repo")
    source = tmp_path / "RSIAtlas"
    source.write_bytes(b"release-swift-binary")
    destination = tmp_path / "dist" / "RSIAtlas"
    destination.parent.mkdir()
    destination.write_text("preserve", encoding="utf-8")

    with pytest.raises(ValueError, match=r"destination must end in \.app"):
        assemble_release_app(
            source_executable=source,
            destination_bundle=destination,
            version="0.1.0",
            build_number="1",
            repo_root=repo_root,
            created_at=NOW,
        )

    assert destination.read_text(encoding="utf-8") == "preserve"


def test_assemble_release_app_replaces_only_exact_bundle(tmp_path: Path) -> None:
    repo_root = _repo_fixture(tmp_path / "repo")
    source = tmp_path / "RSIAtlas"
    source.write_bytes(b"new-release-binary")
    destination = tmp_path / "dist" / "RSIAtlas.app"
    stale = destination / "Contents" / "stale.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("stale", encoding="utf-8")
    sibling = destination.parent / "preserve.txt"
    sibling.write_text("preserve", encoding="utf-8")

    assemble_release_app(
        source_executable=source,
        destination_bundle=destination,
        version="0.1.0",
        build_number="2",
        repo_root=repo_root,
        created_at=NOW,
    )

    assert not stale.exists()
    assert sibling.read_text(encoding="utf-8") == "preserve"


def test_assemble_release_app_cli_stages_supplied_binary(tmp_path: Path) -> None:
    repo_root = _repo_fixture(tmp_path / "repo")
    source = tmp_path / "RSIAtlas"
    source.write_bytes(b"release-swift-binary")
    destination = tmp_path / "dist" / "RSIAtlas.app"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "script" / "assemble_release_app.py"),
            "--repo-root",
            str(repo_root),
            "--source-executable",
            str(source),
            "--destination",
            str(destination),
            "--version",
            "0.1.0",
            "--build-number",
            "9",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert destination.is_dir()
    assert "runtime_complete=false" in result.stdout
    assert "embedded_python_missing" in result.stdout
