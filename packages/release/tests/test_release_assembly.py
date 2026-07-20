"""Versioned macOS release-shell assembly tests."""

from __future__ import annotations

import json
import os
import plistlib
import struct
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


def _thin_arm64_mach_o(*, file_type: int) -> bytes:
    load_command = struct.pack("<II", 0x1B, 24) + (b"\0" * 16)
    return (
        b"\xcf\xfa\xed\xfe"
        + struct.pack(
            "<iiIIIII",
            0x0100000C,
            0,
            file_type,
            1,
            len(load_command),
            0,
            0,
        )
        + load_command
    )


def _runtime_payload_fixture(path: Path) -> Path:
    components = {
        Path("Contents/Resources/runtime/python/bin/python3"): 2,
        Path("Contents/MacOS/RSIAtlasEngine"): 2,
        Path("Contents/Resources/runtime/postgresql/bin/postgres"): 2,
        Path("Contents/Resources/runtime/postgresql/lib/postgresql/vector.dylib"): 6,
    }
    for relative_path, file_type in components.items():
        component = path / relative_path
        component.parent.mkdir(parents=True, exist_ok=True)
        source = path / f"{component.name}.c"
        source.write_text(
            "int main(void) { return 0; }\n"
            if file_type == 2
            else "int vector_sample(void) { return 0; }\n",
            encoding="utf-8",
        )
        arguments = ["/usr/bin/clang", "-arch", "arm64"]
        if file_type != 2:
            arguments.extend(["-dynamiclib", "-install_name", f"@rpath/{component.name}"])
        subprocess.run(
            [*arguments, str(source), "-o", str(component)],
            check=True,
            capture_output=True,
            text=True,
        )
        source.unlink()
    site_packages = (
        path
        / "Contents"
        / "Resources"
        / "runtime"
        / "python"
        / "lib"
        / "python3.12"
        / "site-packages"
    )
    package = site_packages / "rsi_atlas_engine"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "pipeline.py").write_text("", encoding="utf-8")
    legal = path / "Contents" / "Resources" / "Legal" / "third-party"
    legal.mkdir(parents=True)
    (legal / "CPython-LICENSE.txt").write_text("PSF license\n", encoding="utf-8")
    (legal / "PostgreSQL-COPYRIGHT.txt").write_text("PostgreSQL license\n", encoding="utf-8")
    (legal / "pgvector-LICENSE.txt").write_text("PostgreSQL license\n", encoding="utf-8")
    provenance = path / "Contents" / "Resources" / "runtime-build-inputs.json"
    provenance.write_text(
        '{"schema_version":"rsi-atlas.runtime-build-inputs.v1"}\n',
        encoding="utf-8",
    )
    app_resources = path / "Contents" / "Resources" / "app"
    migrations = app_resources / "migrations"
    migrations.mkdir(parents=True)
    migration_names = (
        "foundation",
        "immutable_artifact_contents",
        "document_admission",
        "document_admission_invariants",
        "document_preflight",
        "canonical_documents",
        "chunk_sets",
        "retrieval_indexes",
        "retrieval_research_runs",
        "structured_observations",
        "monitoring_alerts",
        "research_workflow_attempts",
    )
    for number, name in enumerate(migration_names, start=1):
        (migrations / f"{number:04d}_{name}.sql").write_text(
            f"SELECT {number};\n", encoding="utf-8"
        )
    security = app_resources / "security"
    security.mkdir()
    (security / "document-worker.sb").write_text("(version 1)\n", encoding="utf-8")
    inventory = {
        candidate.relative_to(app_resources).as_posix(): sha256(candidate.read_bytes()).hexdigest()
        for candidate in sorted(app_resources.rglob("*"))
        if candidate.is_file()
    }
    (app_resources / "resource-manifest.json").write_text(
        json.dumps(
            {"files": inventory, "schema_version": "rsi-atlas.resource-manifest.v1"},
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
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
            "runtime_dependency_closure_unverified",
        ],
        "build_number": "1",
        "bundle_identifier": "ai.rsitech.RSIAtlas",
        "executable_sha256": sha256(source.read_bytes()).hexdigest(),
        "honesty_label": "runtime_unverified",
        "runtime_dependency_closure_verified": False,
        "runtime_entrypoints_present": False,
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


def test_assemble_release_app_copies_validated_runtime_payload(tmp_path: Path) -> None:
    repo_root = _repo_fixture(tmp_path / "repo")
    source = tmp_path / "RSIAtlas"
    source.write_bytes(b"release-swift-binary")
    payload = _runtime_payload_fixture(tmp_path / "runtime-payload")
    destination = tmp_path / "dist" / "RSIAtlas.app"

    assemble_release_app(
        source_executable=source,
        destination_bundle=destination,
        version="0.1.0",
        build_number="8",
        repo_root=repo_root,
        runtime_payload=payload,
        created_at=NOW,
    )

    manifest = json.loads(
        (destination / "Contents" / "Resources" / "release-assembly.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["runtime_entrypoints_present"] is True
    assert manifest["runtime_dependency_closure_verified"] is True
    assert manifest["blockers"] == []
    assert (
        destination / "Contents" / "Resources" / "runtime" / "python" / "bin" / "python3"
    ).read_bytes() == (
        payload / "Contents" / "Resources" / "runtime" / "python" / "bin" / "python3"
    ).read_bytes()
    assert (
        destination / "Contents" / "Resources" / "Legal" / "third-party" / "CPython-LICENSE.txt"
    ).is_file()
    assert (destination / "Contents" / "Resources" / "runtime-build-inputs.json").is_file()
    assert (
        destination / "Contents" / "Resources" / "app" / "migrations" / "0001_foundation.sql"
    ).is_file()
    assert (
        destination / "Contents" / "Resources" / "app" / "security" / "document-worker.sb"
    ).is_file()


def test_runtime_payload_rejects_missing_migration_before_replacement(tmp_path: Path) -> None:
    repo_root = _repo_fixture(tmp_path / "repo")
    source = tmp_path / "RSIAtlas"
    source.write_bytes(b"release-swift-binary")
    payload = _runtime_payload_fixture(tmp_path / "runtime-payload")
    (
        payload
        / "Contents"
        / "Resources"
        / "app"
        / "migrations"
        / "0012_research_workflow_attempts.sql"
    ).unlink()
    destination = tmp_path / "dist" / "RSIAtlas.app"
    preserved = destination / "Contents" / "preserved"
    preserved.parent.mkdir(parents=True)
    preserved.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="resource inventory"):
        assemble_release_app(
            source_executable=source,
            destination_bundle=destination,
            version="0.1.0",
            build_number="8",
            repo_root=repo_root,
            runtime_payload=payload,
            created_at=NOW,
        )

    assert preserved.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    "contaminant",
    [
        "pytest",
        "_pytest",
        "mypy",
        "ruff",
        "pip",
        "_editable_rsi_atlas.pth",
    ],
)
def test_runtime_payload_rejects_development_or_mutating_python_artifacts(
    tmp_path: Path,
    contaminant: str,
) -> None:
    repo_root = _repo_fixture(tmp_path / "repo")
    source = tmp_path / "RSIAtlas"
    source.write_bytes(b"release-swift-binary")
    payload = _runtime_payload_fixture(tmp_path / "runtime-payload")
    site_packages = (
        payload
        / "Contents"
        / "Resources"
        / "runtime"
        / "python"
        / "lib"
        / "python3.12"
        / "site-packages"
    )
    candidate = site_packages / contaminant
    if candidate.suffix:
        candidate.write_text("/private/source/path\n", encoding="utf-8")
    else:
        candidate.mkdir()
    destination = tmp_path / "dist" / "RSIAtlas.app"

    with pytest.raises(ValueError, match="forbidden Python runtime artifact"):
        assemble_release_app(
            source_executable=source,
            destination_bundle=destination,
            version="0.1.0",
            build_number="8",
            repo_root=repo_root,
            runtime_payload=payload,
            created_at=NOW,
        )

    assert not destination.exists()


def test_runtime_payload_rejects_any_symlink_without_replacing_existing_bundle(
    tmp_path: Path,
) -> None:
    repo_root = _repo_fixture(tmp_path / "repo")
    source = tmp_path / "RSIAtlas"
    source.write_bytes(b"release-swift-binary")
    payload = _runtime_payload_fixture(tmp_path / "runtime-payload")
    external = tmp_path / "external-library"
    external.write_bytes(b"external")
    (payload / "Contents" / "Resources" / "runtime" / "python" / "external").symlink_to(external)
    destination = tmp_path / "dist" / "RSIAtlas.app"
    preserved = destination / "Contents" / "preserved"
    preserved.parent.mkdir(parents=True)
    preserved.write_text("preserve", encoding="utf-8")

    with pytest.raises(ValueError, match="runtime payload must not contain symlinks"):
        assemble_release_app(
            source_executable=source,
            destination_bundle=destination,
            version="0.1.0",
            build_number="8",
            repo_root=repo_root,
            runtime_payload=payload,
            created_at=NOW,
        )

    assert preserved.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize(
    ("relative_path", "content"),
    [
        ("nested/escape.pth", "/private/source/path\n"),
        ("nested/editable.egg-link", "/private/source/path\n"),
        (
            "rsi_atlas_engine-0.1.0.dist-info/direct_url.json",
            '{"dir_info":{"editable":true},"url":"file:///private/source"}\n',
        ),
        ("bin/atlas", "#!/Users/builder/python\n"),
    ],
)
def test_runtime_payload_recursively_rejects_path_injection_artifacts(
    tmp_path: Path,
    relative_path: str,
    content: str,
) -> None:
    repo_root = _repo_fixture(tmp_path / "repo")
    source = tmp_path / "RSIAtlas"
    source.write_bytes(b"release-swift-binary")
    payload = _runtime_payload_fixture(tmp_path / "runtime-payload")
    candidate = (
        payload
        / "Contents"
        / "Resources"
        / "runtime"
        / "python"
        / "lib"
        / "python3.12"
        / "site-packages"
        / relative_path
    )
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden Python runtime artifact"):
        assemble_release_app(
            source_executable=source,
            destination_bundle=tmp_path / "dist" / "RSIAtlas.app",
            version="0.1.0",
            build_number="8",
            repo_root=repo_root,
            runtime_payload=payload,
            created_at=NOW,
        )


def test_runtime_payload_rejects_special_files(tmp_path: Path) -> None:
    repo_root = _repo_fixture(tmp_path / "repo")
    source = tmp_path / "RSIAtlas"
    source.write_bytes(b"release-swift-binary")
    payload = _runtime_payload_fixture(tmp_path / "runtime-payload")
    fifo = payload / "Contents" / "Resources" / "runtime" / "python" / "runtime.fifo"
    os.mkfifo(fifo, mode=0o600)

    with pytest.raises(ValueError, match="regular files and directories"):
        assemble_release_app(
            source_executable=source,
            destination_bundle=tmp_path / "dist" / "RSIAtlas.app",
            version="0.1.0",
            build_number="8",
            repo_root=repo_root,
            runtime_payload=payload,
            created_at=NOW,
        )


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
    assert "runtime_entrypoints_present=false" in result.stdout
    assert "embedded_python_missing" in result.stdout
