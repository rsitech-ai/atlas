#!/usr/bin/env python3
"""Run sealed-holdout promotion suites for §35 components (offline fixtures)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from rsi_atlas_contracts import SealedComponentKind
from rsi_atlas_evaluation.sealed_promotion import run_sealed_promotion

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = tuple(SealedComponentKind)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--component",
        choices=[c.value for c in COMPONENTS] + ["all"],
        default="all",
    )
    parser.add_argument(
        "--allow-synthetic-promote",
        action="store_true",
        help="Exercise promote_production path on synthetic fixture (machinery only).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional directory for evidence JSON dumps",
    )
    args = parser.parse_args(argv)
    now = datetime.now(tz=UTC)
    selected = list(COMPONENTS) if args.component == "all" else [SealedComponentKind(args.component)]
    candidates = {
        SealedComponentKind.EMBEDDING: ("oss_token_hash_v1", "1.0.0"),
        SealedComponentKind.RERANKER: ("lexical_overlap_rerank_v1", "1.0.0"),
        SealedComponentKind.PARSER: ("tier0_pypdf", "1.0.0"),
        SealedComponentKind.CHUNK_POLICY: ("fixed_token", "1.0.0"),
    }
    exit_code = 0
    for component in selected:
        candidate_id, version = candidates[component]
        evidence = run_sealed_promotion(
            component=component,
            candidate_id=candidate_id,
            candidate_version=version,
            repo_root=ROOT,
            created_at=now,
            allow_synthetic_promote=args.allow_synthetic_promote,
        )
        summary = {
            "component": evidence.component.value,
            "candidate_id": evidence.candidate_id,
            "status": evidence.status.value,
            "outcome": evidence.outcome.value,
            "authorizes_production": evidence.authorizes_production(),
            "critical_failure_count": evidence.critical_failure_count,
            "honesty_note": evidence.honesty_note,
            "evidence_id": evidence.evidence_id,
        }
        print(json.dumps(summary, indent=2, sort_keys=True))
        if args.out is not None:
            args.out.mkdir(parents=True, exist_ok=True)
            out_path = args.out / f"{component.value}_sealed_evidence.json"
            out_path.write_bytes(evidence.model_dump_json(indent=2).encode("utf-8"))
        if evidence.status.value == "fail_closed":
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
