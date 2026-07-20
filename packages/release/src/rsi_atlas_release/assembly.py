"""Pure release-bundle assembly and completeness boundaries."""

from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
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
_VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_BUILD_PATTERN = re.compile(r"^[1-9][0-9]*$")


def inspect_runtime_completeness(bundle_path: Path) -> tuple[str, ...]:
    """Return stable blocker codes for absent or empty embedded runtime components."""
    blockers: list[str] = []
    for blocker, relative_path in REQUIRED_RUNTIME_COMPONENTS.items():
        component = bundle_path / relative_path
        if not component.is_file() or component.stat().st_size == 0:
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

    blockers = inspect_runtime_completeness(staged_bundle)
    manifest = {
        "blockers": list(blockers),
        "build_number": build_number,
        "bundle_identifier": "ai.rsitech.RSIAtlas",
        "executable_sha256": sha256(executable.read_bytes()).hexdigest(),
        "honesty_label": "complete_runtime" if not blockers else "incomplete_runtime",
        "runtime_complete": not blockers,
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
    """Atomically stage the versioned native shell without overstating runtime completeness."""
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
