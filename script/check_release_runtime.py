#!/usr/bin/env python3
"""Fail unless a staged RSI Atlas app contains every required embedded runtime component."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rsi_atlas_release import (
    RUNTIME_DEPENDENCY_CLOSURE_BLOCKER,
    inspect_runtime_entrypoints,
    validate_runtime_payload,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    entrypoint_blockers = inspect_runtime_entrypoints(args.bundle)
    closure_verified = False
    if not entrypoint_blockers:
        try:
            validate_runtime_payload(args.bundle)
            closure_verified = True
        except ValueError:
            blockers = [*entrypoint_blockers, "runtime_payload_invalid"]
        else:
            blockers = list(entrypoint_blockers)
    else:
        blockers = list(entrypoint_blockers)
    if not closure_verified:
        blockers.append(RUNTIME_DEPENDENCY_CLOSURE_BLOCKER)
    runtime_ready = not blockers
    payload = {
        "blockers": blockers,
        "bundle": args.bundle.as_posix(),
        "runtime_dependency_closure_verified": closure_verified,
        "runtime_entrypoints_present": not entrypoint_blockers,
        "runtime_ready_for_signing": runtime_ready,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"runtime_ready_for_signing={str(runtime_ready).lower()}")
    return 0 if runtime_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
