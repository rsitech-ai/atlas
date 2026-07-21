#!/usr/bin/env python3
"""Build and atomically stage the versioned RSI Atlas macOS application shell."""

from __future__ import annotations

import argparse
import json
import subprocess
import tomllib
from pathlib import Path

from rsi_atlas_release import assemble_release_app


def _workspace_version(repo_root: Path) -> str:
    document = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    return str(document["project"]["version"])


def _build_release_executable(repo_root: Path) -> Path:
    package_path = repo_root / "apps" / "macos"
    subprocess.run(
        [
            "swift",
            "build",
            "-c",
            "release",
            "--package-path",
            str(package_path),
            "--product",
            "RSIAtlas",
        ],
        cwd=repo_root,
        check=True,
    )
    bin_path = subprocess.run(
        [
            "swift",
            "build",
            "-c",
            "release",
            "--package-path",
            str(package_path),
            "--show-bin-path",
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return Path(bin_path) / "RSIAtlas"


def main() -> int:
    default_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=default_root)
    parser.add_argument("--source-executable", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--runtime-payload", type=Path)
    parser.add_argument("--version")
    parser.add_argument("--build-number", required=True)
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    source = args.source_executable or _build_release_executable(repo_root)
    destination = args.destination or (repo_root / "dist" / "RSIAtlas.app")
    version = args.version or _workspace_version(repo_root)
    bundle = assemble_release_app(
        source_executable=source,
        destination_bundle=destination,
        version=version,
        build_number=args.build_number,
        repo_root=repo_root,
        runtime_payload=args.runtime_payload,
    )
    manifest_path = bundle / "Contents" / "Resources" / "release-assembly.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    blockers = ",".join(manifest["blockers"])
    entrypoints_present = str(manifest["runtime_entrypoints_present"]).lower()
    closure_verified = str(manifest["runtime_dependency_closure_verified"]).lower()
    print(f"assembled {bundle}")
    print(f"runtime_entrypoints_present={entrypoints_present}")
    print(f"runtime_dependency_closure_verified={closure_verified}")
    print(f"blockers={blockers}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
