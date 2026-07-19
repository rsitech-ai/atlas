"""Generate a CycloneDX-ish SBOM from uv.lock without network."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from rsi_atlas_contracts import SbomComponent, SbomDocument, sbom_id

_PACKAGE_RE = re.compile(r'^name = "([^"]+)"\s*$', re.MULTILINE)
_VERSION_RE = re.compile(r'^version = "([^"]+)"\s*$', re.MULTILINE)


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
