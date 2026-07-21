from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from rsi_atlas_release.runtime_builder import (
    RuntimeBuildInputs,
    _adhoc_sign_macho,
    _copy_release_resources,
    _materialize_absolute_dependency,
    _source_token_dependency,
    compile_engine_launcher,
)

ROOT = Path(__file__).resolve().parents[3]


def test_native_launcher_uses_only_in_bundle_isolated_python(tmp_path: Path) -> None:
    bundle = tmp_path / "RSIAtlas.app"
    launcher = bundle / "Contents" / "MacOS" / "RSIAtlasEngine"
    python = bundle / "Contents" / "Resources" / "runtime" / "python" / "bin" / "python3"
    capture = tmp_path / "argv.txt"
    resource_capture = tmp_path / "resource-root.txt"
    runtime_capture = tmp_path / "runtime-root.txt"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > "
        + repr(str(capture))
        + "\nprintf '%s\\n' \"$RSI_ATLAS_RESOURCE_ROOT\" > "
        + repr(str(resource_capture))
        + "\nprintf '%s\\n' \"$RSI_ATLAS_RUNTIME_ROOT\" > "
        + repr(str(runtime_capture))
        + "\n",
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
        "-B",
        "-s",
        "-m",
        "rsi_atlas_engine",
        "doctor",
        "--json",
    ]
    assert resource_capture.read_text(encoding="utf-8").strip() == str(
        bundle / "Contents" / "Resources" / "app"
    )
    assert runtime_capture.read_text(encoding="utf-8").strip() == str(
        bundle / "Contents" / "Resources" / "runtime"
    )


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


def test_materialized_provider_remembers_pristine_hash_after_staged_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cellar = tmp_path / "Cellar"
    keg = cellar / "sample" / "1.0"
    source = keg / "lib" / "libsample.dylib"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"pristine")
    (keg / "INSTALL_RECEIPT.json").write_text("{}", encoding="utf-8")
    (keg / "LICENSE").write_text("license", encoding="utf-8")
    roots = []
    for name in ("python", "postgresql", "pgvector"):
        root = tmp_path / name
        root.mkdir()
        roots.append(root)
    inputs = RuntimeBuildInputs(tmp_path, *roots)
    payload = tmp_path / "payload"
    providers: dict[str, dict[str, object]] = {}
    materialized: dict[Path, tuple[Path, str]] = {}
    monkeypatch.setattr(
        "rsi_atlas_release.runtime_builder._homebrew_provider",
        lambda _path: ("sample", "1.0", keg, Path("lib/libsample.dylib")),
    )

    destination = _materialize_absolute_dependency(
        dependency=str(source),
        inputs=inputs,
        payload=payload,
        providers=providers,
        materialized_sources=materialized,
    )
    destination.write_bytes(b"relocated")
    repeated = _materialize_absolute_dependency(
        dependency=str(source),
        inputs=inputs,
        payload=payload,
        providers=providers,
        materialized_sources=materialized,
    )

    assert repeated == destination
    assert repeated.read_bytes() == b"relocated"
    source.write_bytes(b"different-provider-content")
    with pytest.raises(ValueError, match="destination collision"):
        _materialize_absolute_dependency(
            dependency=str(source),
            inputs=inputs,
            payload=payload,
            providers=providers,
            materialized_sources=materialized,
        )


def test_provider_loader_alias_resolves_to_regular_keg_file(tmp_path: Path) -> None:
    library = tmp_path / "libsample.1.2.dylib"
    alias = tmp_path / "libsample.1.dylib"
    loader = tmp_path / "libconsumer.dylib"
    library.write_bytes(b"library")
    alias.symlink_to(library.name)
    loader.write_bytes(b"loader")

    resolved = _source_token_dependency(
        name="@loader_path/libsample.1.dylib",
        source_image=loader,
        rpaths=(),
    )

    assert resolved == library
    assert resolved.is_file()
    assert not resolved.is_symlink()


def test_modified_arm64_library_is_adhoc_signed_for_staging(tmp_path: Path) -> None:
    source = tmp_path / "sample.c"
    library = tmp_path / "libsample.dylib"
    source.write_text("int sample(void) { return 1; }\n", encoding="utf-8")
    subprocess.run(
        [
            "/usr/bin/clang",
            "-arch",
            "arm64",
            "-dynamiclib",
            str(source),
            "-o",
            str(library),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["/usr/bin/install_name_tool", "-id", "@rpath/libsample.dylib", str(library)],
        check=True,
        capture_output=True,
        text=True,
    )

    _adhoc_sign_macho(library)

    subprocess.run(
        ["/usr/bin/codesign", "--verify", "--strict", str(library)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_release_resources_include_only_operational_inputs(tmp_path: Path) -> None:
    payload = tmp_path / "payload"
    unused = tmp_path / "unused"
    unused.mkdir()
    inputs = RuntimeBuildInputs(ROOT, unused, unused, unused)

    inventory = _copy_release_resources(inputs, payload)

    resource_root = payload / "Contents" / "Resources" / "app"
    assert "migrations/0001_foundation.sql" in inventory
    assert "security/document-worker.sb" in inventory
    assert not (resource_root / "fixtures").exists()
    assert not (resource_root / "docs").exists()
    assert not (resource_root / "uv.lock").exists()
    assert (resource_root / "resource-manifest.json").is_file()
