"""SBOM generation and fail-closed unsigned release checks."""

from rsi_atlas_release.assembly import (
    REQUIRED_RUNTIME_COMPONENTS,
    RUNTIME_DEPENDENCY_CLOSURE_BLOCKER,
    assemble_release_app,
    inspect_runtime_entrypoints,
    validate_runtime_payload,
)
from rsi_atlas_release.checks import run_release_check
from rsi_atlas_release.inventory import inventory_staged_bundle
from rsi_atlas_release.runtime_builder import (
    RuntimeBuildInputs,
    build_runtime_payload,
    compile_engine_launcher,
)
from rsi_atlas_release.sbom import build_sbom_from_lock, parse_uv_lock_components

__all__ = [
    "REQUIRED_RUNTIME_COMPONENTS",
    "RUNTIME_DEPENDENCY_CLOSURE_BLOCKER",
    "RuntimeBuildInputs",
    "assemble_release_app",
    "build_runtime_payload",
    "build_sbom_from_lock",
    "compile_engine_launcher",
    "inspect_runtime_entrypoints",
    "inventory_staged_bundle",
    "parse_uv_lock_components",
    "run_release_check",
    "validate_runtime_payload",
]
