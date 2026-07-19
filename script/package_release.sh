#!/usr/bin/env bash
# Stage + fail-closed release check. Never claims notarized without secrets.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p dist
uv run python script/release_check.py --require-release
echo "package_release: release_ready remains false until signing/notarization secrets + proofs exist."
echo "see docs/release/signing-notarization-blockers.md"
