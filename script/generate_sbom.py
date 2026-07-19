#!/usr/bin/env python3
"""Generate CycloneDX-ish SBOM JSON from uv.lock (no network)."""

from __future__ import annotations

import argparse
from pathlib import Path

from rsi_atlas_release import build_sbom_from_lock


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lock",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "uv.lock",
    )
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    doc = build_sbom_from_lock(args.lock)
    args.out.write_bytes(doc.model_dump_json(indent=2).encode("utf-8"))
    print(f"wrote {args.out} with {len(doc.components)} components")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
