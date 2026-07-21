#!/usr/bin/env python3
"""Fail unless a staged RSI Atlas app contains every required embedded runtime component."""

from __future__ import annotations

import argparse
import json
import plistlib
from pathlib import Path

from rsi_atlas_contracts import SbomDocument
from rsi_atlas_release import (
    RUNTIME_DEPENDENCY_CLOSURE_BLOCKER,
    inspect_runtime_entrypoints,
    validate_runtime_payload,
    verify_artifact_sbom,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    bundle = args.bundle.resolve(strict=True)
    entrypoint_blockers = inspect_runtime_entrypoints(bundle)
    closure_verified = False
    if not entrypoint_blockers:
        try:
            validate_runtime_payload(bundle)
            closure_verified = True
        except ValueError:
            blockers = [*entrypoint_blockers, "runtime_payload_invalid"]
        else:
            blockers = list(entrypoint_blockers)
    else:
        blockers = list(entrypoint_blockers)
    if not closure_verified:
        blockers.append(RUNTIME_DEPENDENCY_CLOSURE_BLOCKER)
    artifact_sbom_verified = False
    try:
        sbom_path = bundle / "Contents" / "Resources" / "sbom.cdx.json"
        sbom = SbomDocument.model_validate_json(sbom_path.read_text(encoding="utf-8"))
        plist = plistlib.loads((bundle / "Contents" / "Info.plist").read_bytes())
        verify_artifact_sbom(
            bundle,
            sbom,
            lock_path=repo_root / "uv.lock",
            version=str(plist["CFBundleShortVersionString"]),
        )
        artifact_sbom_verified = True
    except (KeyError, OSError, TypeError, ValueError, plistlib.InvalidFileException):
        blockers.append("artifact_sbom_invalid")
    runtime_ready = not blockers
    payload = {
        "artifact_sbom_verified": artifact_sbom_verified,
        "blockers": blockers,
        "bundle": bundle.as_posix(),
        "runtime_dependency_closure_verified": closure_verified,
        "runtime_entrypoints_present": not entrypoint_blockers,
        "runtime_ready_for_signing": runtime_ready,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"artifact_sbom_verified={str(artifact_sbom_verified).lower()}")
    print(f"runtime_ready_for_signing={str(runtime_ready).lower()}")
    return 0 if runtime_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
