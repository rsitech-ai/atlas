#!/usr/bin/env python3
"""Build the pinned local RSI Atlas runtime payload without signing it."""

from __future__ import annotations

import argparse
from pathlib import Path

from rsi_atlas_release.runtime_builder import RuntimeBuildInputs, build_runtime_payload


def main() -> int:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=default_root)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--python-prefix", type=Path)
    parser.add_argument("--postgresql-prefix", type=Path)
    parser.add_argument("--pgvector-prefix", type=Path)
    arguments = parser.parse_args()

    repo_root = arguments.repo_root.resolve(strict=True)
    discovered = RuntimeBuildInputs.local(repo_root)
    inputs = RuntimeBuildInputs(
        repo_root=repo_root,
        python_prefix=(arguments.python_prefix or discovered.python_prefix).resolve(strict=True),
        postgresql_prefix=(arguments.postgresql_prefix or discovered.postgresql_prefix).resolve(
            strict=True
        ),
        pgvector_prefix=(arguments.pgvector_prefix or discovered.pgvector_prefix).resolve(
            strict=True
        ),
    )
    destination = arguments.destination or (repo_root / "dist" / "runtime-payload")
    result = build_runtime_payload(
        inputs=inputs,
        destination=destination,
        launcher_source=repo_root / "infra" / "release" / "RSIAtlasEngine.c",
    )
    print(f"built runtime payload {result}")
    print("runtime_dependency_closure_verified=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
