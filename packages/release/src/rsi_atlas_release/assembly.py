"""Pure release-bundle assembly and completeness boundaries."""

from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import struct
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Final

from rsi_atlas_release.sbom import build_sbom_from_lock

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


def _write_staged_bundle(
    *,
    staged_bundle: Path,
    source_executable: Path,
    version: str,
    build_number: str,
    repo_root: Path,
    created_at: datetime,
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
    sbom = build_sbom_from_lock(repo_root / "uv.lock", created_at=created_at)
    (resources / "sbom.cdx.json").write_text(
        sbom.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    entrypoint_blockers = inspect_runtime_entrypoints(staged_bundle)
    manifest = {
        "blockers": [*entrypoint_blockers, RUNTIME_DEPENDENCY_CLOSURE_BLOCKER],
        "build_number": build_number,
        "bundle_identifier": "ai.rsitech.RSIAtlas",
        "executable_sha256": sha256(executable.read_bytes()).hexdigest(),
        "honesty_label": "runtime_unverified",
        "runtime_dependency_closure_verified": False,
        "runtime_entrypoints_present": not entrypoint_blockers,
        "schema_version": "rsi-atlas.release-assembly.v1",
        "version": version,
    }
    (resources / "release-assembly.json").write_text(
        json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )


def assemble_release_app(
    *,
    source_executable: Path,
    destination_bundle: Path,
    version: str,
    build_number: str,
    repo_root: Path,
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
