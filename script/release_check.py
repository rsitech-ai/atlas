#!/usr/bin/env python3
"""Fail-closed release check. Exits non-zero when --require-release is set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rsi_atlas_release import run_release_check


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--require-release",
        action="store_true",
        help="Claim release-candidate readiness (always fails closed without secrets).",
    )
    args = parser.parse_args()
    report = run_release_check(
        repo_root=args.repo_root,
        require_release=args.require_release,
    )
    print(json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True))
    if args.require_release:
        return 1
    return 0 if report.claim.value == "development_only" else 1


if __name__ == "__main__":
    raise SystemExit(main())
