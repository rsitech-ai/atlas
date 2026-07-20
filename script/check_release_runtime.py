#!/usr/bin/env python3
"""Fail unless a staged RSI Atlas app contains every required embedded runtime component."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rsi_atlas_release import inspect_runtime_completeness


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    args = parser.parse_args()
    blockers = inspect_runtime_completeness(args.bundle)
    payload = {
        "blockers": list(blockers),
        "bundle": args.bundle.as_posix(),
        "runtime_complete": not blockers,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    print(f"runtime_complete={str(not blockers).lower()}")
    return 1 if blockers else 0


if __name__ == "__main__":
    raise SystemExit(main())
