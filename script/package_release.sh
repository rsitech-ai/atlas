#!/usr/bin/env bash
# Assemble + fail-closed release check. Never claims notarized without proofs.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
mkdir -p dist
BUILD_NUMBER="${RSI_ATLAS_BUILD_NUMBER:-$(git rev-list --count HEAD)}"
RUNTIME_PAYLOAD="$ROOT_DIR/dist/runtime-payload"
uv run python script/build_release_runtime.py --destination "$RUNTIME_PAYLOAD"
uv run python script/assemble_release_app.py \
  --runtime-payload "$RUNTIME_PAYLOAD" \
  --build-number "$BUILD_NUMBER"
if ! uv run python script/release_check.py --require-release; then
  echo "package_release: blocked; the assembled app is not a releasable download." >&2
  echo "see dist/RSIAtlas.app/Contents/Resources/release-assembly.json" >&2
  echo "see docs/release/signing-notarization-blockers.md" >&2
  exit 1
fi
echo "package_release: release-candidate gate passed"
