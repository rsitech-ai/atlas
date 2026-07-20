"""Pure release-bundle assembly and completeness boundaries."""

from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import stat
import struct
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Final

from rsi_atlas_release.macho import (
    MachOParseError,
    remove_non_system_rpaths,
    verify_macho_closure,
)
from rsi_atlas_release.sbom import build_sbom_from_artifact, build_sbom_from_lock

REQUIRED_RUNTIME_COMPONENTS: Final[Mapping[str, Path]] = MappingProxyType(
    {
        "embedded_python_missing": Path("Contents/Resources/runtime/python/bin/python3"),
        "engine_launcher_missing": Path("Contents/MacOS/RSIAtlasEngine"),
        "postgresql_missing": Path("Contents/Resources/runtime/postgresql/bin/postgres"),
        "pgvector_missing": Path(
            "Contents/Resources/runtime/postgresql/lib/postgresql/vector.dylib"
        ),
    }
)
RUNTIME_DEPENDENCY_CLOSURE_BLOCKER: Final = "runtime_dependency_closure_unverified"
_VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_BUILD_PATTERN = re.compile(r"^[1-9][0-9]*$")
_EXPECTED_MACH_O_FILE_TYPES: Final[Mapping[str, frozenset[int]]] = MappingProxyType(
    {
        "embedded_python_missing": frozenset({2}),
        "engine_launcher_missing": frozenset({2}),
        "postgresql_missing": frozenset({2}),
        "pgvector_missing": frozenset({6, 8}),
    }
)
_EXECUTABLE_RUNTIME_BLOCKERS: Final[frozenset[str]] = frozenset(
    {
        "embedded_python_missing",
        "engine_launcher_missing",
        "postgresql_missing",
    }
)
_RUNTIME_LEGAL_FILES: Final[tuple[Path, ...]] = (
    Path("Contents/Resources/Legal/third-party/CPython-LICENSE.txt"),
    Path("Contents/Resources/Legal/third-party/PostgreSQL-COPYRIGHT.txt"),
    Path("Contents/Resources/Legal/third-party/pgvector-LICENSE.txt"),
)
_RUNTIME_PROVENANCE_FILE: Final = Path("Contents/Resources/runtime-build-inputs.json")
_RUNTIME_RESOURCE_ROOT: Final = Path("Contents/Resources/app")
_EXPECTED_MIGRATIONS: Final = tuple(
    f"migrations/{number:04d}_{name}.sql"
    for number, name in enumerate(
        (
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
        ),
        start=1,
    )
)
_FORBIDDEN_PYTHON_ARTIFACT_PREFIXES: Final[tuple[str, ...]] = (
    "_pytest",
    "mypy",
    "pip",
    "pytest",
    "ruff",
)


def _mach_o_file_type(path: Path) -> int | None:
    try:
        with path.open("rb") as handle:
            header = handle.read(32)
            if len(header) != 32 or header[:4] != b"\xcf\xfa\xed\xfe":
                return None
            cpu_type, _, file_type, command_count, commands_size, _, _ = struct.unpack(
                "<iiIIIII", header[4:]
            )
            if (
                cpu_type != 0x0100000C
                or not 1 <= command_count <= 4096
                or commands_size < command_count * 8
                or commands_size > 16 * 1024 * 1024
            ):
                return None
            commands = handle.read(commands_size)
    except (OSError, struct.error):
        return None
    if len(commands) != commands_size:
        return None
    offset = 0
    for _ in range(command_count):
        if offset + 8 > commands_size:
            return None
        _, command_size = struct.unpack_from("<II", commands, offset)
        if command_size < 8 or command_size % 8 != 0 or offset + command_size > commands_size:
            return None
        offset += command_size
    return file_type if offset == commands_size else None


def _has_symlink_in_component_path(bundle_path: Path, relative_path: Path) -> bool:
    candidate = bundle_path
    if candidate.is_symlink():
        return True
    for part in relative_path.parts:
        candidate /= part
        if candidate.is_symlink():
            return True
    return False


def inspect_runtime_entrypoints(bundle_path: Path) -> tuple[str, ...]:
    """Validate required in-bundle ARM64 Mach-O entrypoints without claiming they can launch."""
    blockers: list[str] = []
    bundle_root = bundle_path.resolve()
    for blocker, relative_path in REQUIRED_RUNTIME_COMPONENTS.items():
        component = bundle_path / relative_path
        contained = False
        try:
            component.resolve(strict=True).relative_to(bundle_root)
            contained = True
        except (FileNotFoundError, ValueError):
            pass
        if (
            _has_symlink_in_component_path(bundle_path, relative_path)
            or not contained
            or not component.is_file()
            or component.stat().st_size == 0
            or _mach_o_file_type(component) not in _EXPECTED_MACH_O_FILE_TYPES[blocker]
            or (blocker in _EXECUTABLE_RUNTIME_BLOCKERS and component.stat().st_mode & 0o111 == 0)
        ):
            blockers.append(blocker)
    return tuple(blockers)


def _require_source_file(path: Path, *, label: str) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"{label} must be a non-empty file: {path}")


def _validate_release_resources(runtime_payload: Path) -> None:
    root = runtime_payload / _RUNTIME_RESOURCE_ROOT
    manifest_path = root / "resource-manifest.json"
    _require_source_file(manifest_path, label="release resource manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != "rsi-atlas.resource-manifest.v1":
            raise ValueError
        declared = manifest["files"]
        if not isinstance(declared, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in declared.items()
        ):
            raise ValueError
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("release resource manifest is invalid") from error
    actual = {
        candidate.relative_to(root).as_posix(): sha256(candidate.read_bytes()).hexdigest()
        for candidate in sorted(root.rglob("*"))
        if candidate.is_file() and candidate != manifest_path
    }
    expected_paths = {*_EXPECTED_MIGRATIONS, "security/document-worker.sb"}
    if set(actual) != expected_paths or actual != declared:
        raise ValueError("release resource inventory does not match the staged files")


def validate_runtime_payload(runtime_payload: Path) -> None:
    if runtime_payload.is_symlink() or not runtime_payload.is_dir():
        raise ValueError("runtime payload must be a real directory")
    for candidate in runtime_payload.rglob("*"):
        if candidate.is_symlink():
            raise ValueError("runtime payload must not contain symlinks")
        mode = candidate.lstat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise ValueError("runtime payload must contain only regular files and directories")
    blockers = inspect_runtime_entrypoints(runtime_payload)
    if blockers:
        raise ValueError(f"runtime payload entrypoints are invalid: {','.join(blockers)}")
    for relative_path in _RUNTIME_LEGAL_FILES:
        _require_source_file(runtime_payload / relative_path, label=str(relative_path))
    _require_source_file(
        runtime_payload / _RUNTIME_PROVENANCE_FILE,
        label=str(_RUNTIME_PROVENANCE_FILE),
    )
    _validate_release_resources(runtime_payload)

    site_packages = (
        runtime_payload
        / "Contents"
        / "Resources"
        / "runtime"
        / "python"
        / "lib"
        / "python3.12"
        / "site-packages"
    )
    if not site_packages.is_dir():
        raise ValueError("runtime payload site-packages directory is missing")
    for candidate in site_packages.rglob("*"):
        relative = candidate.relative_to(site_packages)
        folded_name = candidate.name.casefold()
        path_parts = tuple(part.casefold() for part in relative.parts)
        forbidden_prefix = bool(path_parts) and path_parts[0].startswith(
            _FORBIDDEN_PYTHON_ARTIFACT_PREFIXES
        )
        if (
            candidate.suffix.casefold() in {".egg-link", ".pth", ".pyc"}
            or folded_name == "direct_url.json"
            or "__pycache__" in path_parts
            or path_parts[:1] == ("bin",)
            or forbidden_prefix
        ):
            raise ValueError(f"forbidden Python runtime artifact: {candidate.name}")
    try:
        verify_macho_closure(runtime_payload)
    except (MachOParseError, ValueError) as error:
        raise ValueError("runtime payload Mach-O closure is invalid") from error


def _copy_runtime_payload(*, runtime_payload: Path, staged_bundle: Path) -> None:
    source_contents = runtime_payload / "Contents"
    destination_contents = staged_bundle / "Contents"
    shutil.copytree(
        source_contents / "Resources" / "runtime",
        destination_contents / "Resources" / "runtime",
    )
    shutil.copy2(
        source_contents / "Resources" / "runtime-build-inputs.json",
        destination_contents / "Resources" / "runtime-build-inputs.json",
    )
    shutil.copytree(
        source_contents / "Resources" / "app",
        destination_contents / "Resources" / "app",
    )
    shutil.copytree(
        source_contents / "Resources" / "Legal" / "third-party",
        destination_contents / "Resources" / "Legal" / "third-party",
    )
    launcher = destination_contents / "MacOS" / "RSIAtlasEngine"
    shutil.copy2(source_contents / "MacOS" / "RSIAtlasEngine", launcher)
    launcher.chmod(launcher.stat().st_mode | 0o111)


def _write_staged_bundle(
    *,
    staged_bundle: Path,
    source_executable: Path,
    version: str,
    build_number: str,
    repo_root: Path,
    created_at: datetime,
    runtime_payload: Path | None,
) -> None:
    contents = staged_bundle / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"
    legal = resources / "Legal"
    legal.mkdir(parents=True)
    macos.mkdir(parents=True)

    executable = macos / "RSIAtlas"
    shutil.copy2(source_executable, executable)
    executable.chmod(executable.stat().st_mode | 0o111)
    remove_non_system_rpaths(executable)

    plist = {
        "CFBundleExecutable": "RSIAtlas",
        "CFBundleIdentifier": "ai.rsitech.RSIAtlas",
        "CFBundleName": "RSI Atlas",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": build_number,
        "LSMinimumSystemVersion": "15.0",
        "NSHighResolutionCapable": True,
        "NSPrincipalClass": "NSApplication",
    }
    (contents / "Info.plist").write_bytes(plistlib.dumps(plist, sort_keys=True))

    shutil.copy2(repo_root / "LICENSE", legal / "LICENSE")
    shutil.copy2(repo_root / "NOTICE", legal / "NOTICE")
    if runtime_payload is not None:
        _copy_runtime_payload(runtime_payload=runtime_payload, staged_bundle=staged_bundle)

    entrypoint_blockers = inspect_runtime_entrypoints(staged_bundle)
    closure_verified = False
    if runtime_payload is not None and not entrypoint_blockers:
        try:
            verify_macho_closure(staged_bundle)
            closure_verified = True
        except (MachOParseError, ValueError):
            closure_verified = False
    blockers = list(entrypoint_blockers)
    if not closure_verified:
        blockers.append(RUNTIME_DEPENDENCY_CLOSURE_BLOCKER)
    manifest = {
        "blockers": blockers,
        "build_number": build_number,
        "bundle_identifier": "ai.rsitech.RSIAtlas",
        "executable_sha256": sha256(executable.read_bytes()).hexdigest(),
        "honesty_label": ("runtime_closure_verified" if closure_verified else "runtime_unverified"),
        "runtime_dependency_closure_verified": closure_verified,
        "runtime_entrypoints_present": not entrypoint_blockers,
        "schema_version": "rsi-atlas.release-assembly.v1",
        "version": version,
    }
    (resources / "release-assembly.json").write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if runtime_payload is None:
        sbom = build_sbom_from_lock(repo_root / "uv.lock", created_at=created_at)
    else:
        sbom = build_sbom_from_artifact(
            staged_bundle,
            lock_path=repo_root / "uv.lock",
            version=version,
            created_at=created_at,
        )
    (resources / "sbom.cdx.json").write_text(
        sbom.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def assemble_release_app(
    *,
    source_executable: Path,
    destination_bundle: Path,
    version: str,
    build_number: str,
    repo_root: Path,
    runtime_payload: Path | None = None,
    created_at: datetime | None = None,
) -> Path:
    """Atomically stage the versioned native shell without claiming runtime dependency closure."""
    if destination_bundle.suffix != ".app":
        raise ValueError("destination must end in .app")
    if _VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError("version must be a three-component semantic version")
    if _BUILD_PATTERN.fullmatch(build_number) is None:
        raise ValueError("build_number must be a positive decimal integer")
    _require_source_file(source_executable, label="source executable")
    for name in ("LICENSE", "NOTICE", "uv.lock"):
        _require_source_file(repo_root / name, label=name)
    if runtime_payload is not None:
        validate_runtime_payload(runtime_payload)

    assembled_at = created_at or datetime.now(tz=UTC)
    if assembled_at.tzinfo is None or assembled_at.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")

    destination_bundle.parent.mkdir(parents=True, exist_ok=True)
    staging_root = Path(
        tempfile.mkdtemp(
            prefix=f".{destination_bundle.name}.stage-",
            dir=destination_bundle.parent,
        )
    )
    staged_bundle = staging_root / destination_bundle.name
    previous_bundle = staging_root / f".{destination_bundle.name}.previous"
    moved_previous = False
    try:
        _write_staged_bundle(
            staged_bundle=staged_bundle,
            source_executable=source_executable,
            version=version,
            build_number=build_number,
            repo_root=repo_root,
            created_at=assembled_at,
            runtime_payload=runtime_payload,
        )
        if os.path.lexists(destination_bundle):
            os.replace(destination_bundle, previous_bundle)
            moved_previous = True
        os.replace(staged_bundle, destination_bundle)
    except Exception:
        if moved_previous and not os.path.lexists(destination_bundle):
            os.replace(previous_bundle, destination_bundle)
        raise
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)
    return destination_bundle
