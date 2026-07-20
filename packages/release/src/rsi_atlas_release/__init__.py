"""SBOM generation and fail-closed unsigned release checks."""

from rsi_atlas_release.assembly import (
    REQUIRED_RUNTIME_COMPONENTS,
    assemble_release_app,
    inspect_runtime_completeness,
)
from rsi_atlas_release.checks import run_release_check
from rsi_atlas_release.inventory import inventory_staged_bundle
from rsi_atlas_release.sbom import build_sbom_from_lock, parse_uv_lock_components

__all__ = [
    "REQUIRED_RUNTIME_COMPONENTS",
    "assemble_release_app",
    "build_sbom_from_lock",
    "inspect_runtime_completeness",
    "inventory_staged_bundle",
    "parse_uv_lock_components",
    "run_release_check",
]
