"""Generate and validate offline CycloneDX release inventories."""

from __future__ import annotations

import csv
import json
import re
from datetime import UTC, datetime
from email.parser import Parser
from hashlib import sha256
from pathlib import Path

from rsi_atlas_contracts import SbomComponent, SbomDocument, SbomFile, sbom_id

_PACKAGE_RE = re.compile(r'^name = "([^"]+)"\s*$', re.MULTILINE)
_VERSION_RE = re.compile(r'^version = "([^"]+)"\s*$', re.MULTILINE)
_ARTIFACT_EXCLUSIONS = ("Contents/Resources/sbom.cdx.json",)


def _tree_hash(entries: tuple[SbomFile, ...]) -> str:
    digest = sha256()
    for entry in entries:
        path = entry.path.encode("utf-8")
        value = entry.sha256.encode("ascii")
        digest.update(len(path).to_bytes(8, "big"))
        digest.update(path)
        digest.update(value)
    return digest.hexdigest()


def _file_inventory(bundle: Path, *, exclusions: tuple[str, ...]) -> tuple[SbomFile, ...]:
    excluded = frozenset(exclusions)
    entries: list[SbomFile] = []
    for candidate in sorted(bundle.rglob("*")):
        relative = candidate.relative_to(bundle).as_posix()
        if candidate.is_symlink():
            raise ValueError(f"artifact SBOM refuses symlinked path: {relative}")
        if candidate.is_file() and relative not in excluded:
            entries.append(
                SbomFile(path=relative, sha256=sha256(candidate.read_bytes()).hexdigest())
            )
    return tuple(entries)


def _directory_hash(bundle: Path, root: Path) -> str:
    entries = tuple(
        SbomFile(
            path=candidate.relative_to(bundle).as_posix(),
            sha256=sha256(candidate.read_bytes()).hexdigest(),
        )
        for candidate in sorted(root.rglob("*"))
        if candidate.is_file()
    )
    if not entries:
        raise ValueError(f"SBOM component tree is empty: {root.name}")
    return _tree_hash(entries)


def _python_components(bundle: Path) -> tuple[SbomComponent, ...]:
    site_packages = (
        bundle
        / "Contents"
        / "Resources"
        / "runtime"
        / "python"
        / "lib"
        / "python3.12"
        / "site-packages"
    )
    components: list[SbomComponent] = []
    for dist_info in sorted(site_packages.glob("*.dist-info")):
        metadata_path = dist_info / "METADATA"
        record_path = dist_info / "RECORD"
        if not metadata_path.is_file() or not record_path.is_file():
            raise ValueError(
                f"installed Python distribution metadata is incomplete: {dist_info.name}"
            )
        metadata = Parser().parsestr(metadata_path.read_text(encoding="utf-8"))
        name = metadata.get("Name", "").strip().lower().replace("_", "-")
        version = metadata.get("Version", "").strip()
        if not name or not version:
            raise ValueError("installed Python distribution identity is incomplete")
        files: list[SbomFile] = []
        with record_path.open(encoding="utf-8", newline="") as stream:
            for row in csv.reader(stream):
                if not row:
                    continue
                candidate = (site_packages / row[0]).resolve(strict=False)
                try:
                    candidate.relative_to(site_packages.resolve(strict=True))
                except ValueError as error:
                    raise ValueError("Python distribution RECORD escapes site-packages") from error
                if candidate.is_file():
                    files.append(
                        SbomFile(
                            path=candidate.relative_to(bundle).as_posix(),
                            sha256=sha256(candidate.read_bytes()).hexdigest(),
                        )
                    )
        if not files:
            raise ValueError(f"installed Python distribution is empty: {name}")
        licenses = tuple(
            candidate.relative_to(bundle).as_posix()
            for candidate in sorted((dist_info / "licenses").rglob("*"))
            if candidate.is_file()
        )
        components.append(
            SbomComponent(
                name=name,
                version=version,
                purl=f"pkg:pypi/{name}@{version}",
                sha256=_tree_hash(tuple(sorted(files, key=lambda item: item.path))),
                license_expression=(metadata.get("License-Expression") or "").strip() or None,
                license_files=licenses,
            )
        )
    if not components:
        raise ValueError("artifact SBOM found no installed Python distributions")
    return tuple(components)


def build_sbom_from_artifact(
    bundle: Path,
    *,
    lock_path: Path,
    version: str,
    created_at: datetime | None = None,
) -> SbomDocument:
    """Describe the exact assembled, pre-sign bundle rather than the development lock universe."""
    raw_lock = lock_path.read_bytes()
    lock_hash = sha256(raw_lock).hexdigest()
    now = created_at or datetime.now(tz=UTC)
    provenance_path = bundle / "Contents" / "Resources" / "runtime-build-inputs.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    runtime = bundle / "Contents" / "Resources" / "runtime"
    legal = bundle / "Contents" / "Resources" / "Legal" / "third-party"
    executable = bundle / "Contents" / "MacOS" / "RSIAtlas"
    components: list[SbomComponent] = [
        SbomComponent(
            name="rsi-atlas",
            version=version,
            purl=f"pkg:generic/rsi-atlas@{version}",
            sha256=sha256(executable.read_bytes()).hexdigest(),
            license_expression="Apache-2.0",
            license_files=(
                "Contents/Resources/Legal/LICENSE",
                "Contents/Resources/Legal/NOTICE",
            ),
        ),
        SbomComponent(
            name="cpython",
            version=str(provenance["python"]["version"]),
            purl=f"pkg:generic/cpython@{provenance['python']['version']}",
            sha256=_directory_hash(bundle, runtime / "python"),
            license_files=("Contents/Resources/Legal/third-party/CPython-LICENSE.txt",),
        ),
        SbomComponent(
            name="postgresql",
            version=str(provenance["postgresql"]["version"]),
            purl=f"pkg:generic/postgresql@{provenance['postgresql']['version']}",
            sha256=_directory_hash(bundle, runtime / "postgresql"),
            license_files=("Contents/Resources/Legal/third-party/PostgreSQL-COPYRIGHT.txt",),
        ),
        SbomComponent(
            name="pgvector",
            version=str(provenance["pgvector"]["version"]),
            purl=f"pkg:generic/pgvector@{provenance['pgvector']['version']}",
            sha256=sha256(
                (runtime / "postgresql" / "lib" / "postgresql" / "vector.dylib").read_bytes()
            ).hexdigest(),
            license_files=("Contents/Resources/Legal/third-party/pgvector-LICENSE.txt",),
        ),
    ]
    for provider in provenance["macho_closure"]["providers"]:
        formula = str(provider["formula"])
        provider_root = runtime / "native" / formula / str(provider["version"])
        components.append(
            SbomComponent(
                name="homebrew-" + formula.replace("@", "-"),
                version=str(provider["version"]),
                purl=(
                    "pkg:generic/homebrew-" + formula.replace("@", "-") + f"@{provider['version']}"
                ),
                sha256=_directory_hash(bundle, provider_root),
                license_files=tuple(
                    (legal / "native" / formula / str(filename)).relative_to(bundle).as_posix()
                    for filename in provider["licenses"]
                ),
            )
        )
    components.extend(_python_components(bundle))
    files = _file_inventory(bundle, exclusions=_ARTIFACT_EXCLUSIONS)
    return SbomDocument(
        sbom_id=sbom_id(source_lock_hash=lock_hash, created_at=now),
        bom_format="CycloneDX",
        spec_version="1.5",
        components=tuple(sorted(components, key=lambda component: component.name)),
        created_at=now,
        source_lock_hash=lock_hash,
        artifact_tree_sha256=_tree_hash(files),
        files=files,
        excluded_paths=_ARTIFACT_EXCLUSIONS,
    )


def verify_artifact_sbom(
    bundle: Path,
    document: SbomDocument,
    *,
    lock_path: Path,
    version: str,
) -> None:
    expected = build_sbom_from_artifact(
        bundle,
        lock_path=lock_path,
        version=version,
        created_at=document.created_at,
    )
    if expected != document:
        raise ValueError("artifact SBOM file inventory does not match the bundle")
    for component in document.components:
        if not component.license_expression and not component.license_files:
            raise ValueError(f"artifact SBOM license evidence is missing: {component.name}")
        for license_path in component.license_files:
            if not (bundle / license_path).is_file():
                raise ValueError(f"artifact SBOM license is missing: {component.name}")


def parse_uv_lock_components(lock_text: str) -> tuple[SbomComponent, ...]:
    """Parse top-level package name/version pairs from uv.lock TOML text.

    ponytail: ceiling is a line-oriented name/version scrape of [[package]] blocks;
    upgrade path is tomllib once uv.lock guarantees a stable TOML shape we want to
    depend on formally, or `uv export --format cyclonedx`.
    """
    components: list[SbomComponent] = []
    blocks = re.split(r"(?=^\[\[package\]\])", lock_text, flags=re.MULTILINE)
    for block in blocks:
        if not block.startswith("[[package]]"):
            continue
        name_match = _PACKAGE_RE.search(block)
        version_match = _VERSION_RE.search(block)
        if name_match is None or version_match is None:
            continue
        name = name_match.group(1)
        version = version_match.group(1)
        components.append(
            SbomComponent(
                name=name,
                version=version,
                purl=f"pkg:pypi/{name}@{version}",
            )
        )
    if not components:
        raise ValueError("uv.lock contained no [[package]] entries")
    # Stable unique by name (first wins)
    seen: set[str] = set()
    unique: list[SbomComponent] = []
    for component in components:
        if component.name in seen:
            continue
        seen.add(component.name)
        unique.append(component)
    return tuple(sorted(unique, key=lambda c: c.name))


def build_sbom_from_lock(
    lock_path: Path,
    *,
    created_at: datetime | None = None,
) -> SbomDocument:
    raw = lock_path.read_bytes()
    lock_hash = sha256(raw).hexdigest()
    now = created_at or datetime.now(tz=UTC)
    components = parse_uv_lock_components(raw.decode("utf-8"))
    return SbomDocument(
        sbom_id=sbom_id(source_lock_hash=lock_hash, created_at=now),
        bom_format="CycloneDX",
        spec_version="1.5",
        components=components,
        created_at=now,
        source_lock_hash=lock_hash,
    )
