#!/usr/bin/env python3
"""Fail unless a staged RSI Atlas app contains every required embedded runtime component."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rsi_atlas_release import (
    RUNTIME_DEPENDENCY_CLOSURE_BLOCKER,
    inspect_runtime_entrypoints,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    entrypoint_blockers = inspect_runtime_entrypoints(args.bundle)
    blockers = (*entrypoint_blockers, RUNTIME_DEPENDENCY_CLOSURE_BLOCKER)
    payload = {
        "blockers": list(blockers),
        "bundle": args.bundle.as_posix(),
        "runtime_dependency_closure_verified": False,
        "runtime_entrypoints_present": not entrypoint_blockers,
        "runtime_ready_for_signing": False,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    print("runtime_ready_for_signing=false")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
