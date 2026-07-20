"""Pure release-bundle assembly and completeness boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final

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


def inspect_runtime_completeness(bundle_path: Path) -> tuple[str, ...]:
    """Return stable blocker codes for absent or empty embedded runtime components."""
    blockers: list[str] = []
    for blocker, relative_path in REQUIRED_RUNTIME_COMPONENTS.items():
        component = bundle_path / relative_path
        if not component.is_file() or component.stat().st_size == 0:
            blockers.append(blocker)
    return tuple(blockers)
