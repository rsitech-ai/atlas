#!/usr/bin/env bash
# Fail-closed Developer ID sign + notarize. Requires Apple secrets.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_BUNDLE="${1:-$ROOT_DIR/dist/RSIAtlas.app}"

if [[ ! -d "$APP_BUNDLE" ]]; then
  echo "missing app bundle: $APP_BUNDLE" >&2
  exit 1
fi
if [[ -z "${RSI_ATLAS_SIGNING_IDENTITY:-}" ]]; then
  echo "RSI_ATLAS_SIGNING_IDENTITY is required; see docs/release/signing-notarization-blockers.md" >&2
  exit 2
fi
if [[ -z "${RSI_ATLAS_NOTARY_KEY:-}" || -z "${RSI_ATLAS_NOTARY_KEY_ID:-}" || -z "${RSI_ATLAS_NOTARY_ISSUER:-}" ]]; then
  echo "notary env (RSI_ATLAS_NOTARY_KEY/KEY_ID/ISSUER) required; refusing unsigned notarization claim" >&2
  exit 2
fi

echo "signing $APP_BUNDLE with Developer ID (nested codesign required for release proof)…"
# ponytail: ceiling=shallow codesign of outer bundle only; upgrade=full nested runtime + hardened entitlements
codesign --force --deep --options runtime --sign "$RSI_ATLAS_SIGNING_IDENTITY" "$APP_BUNDLE"
codesign --verify --deep --strict "$APP_BUNDLE"

ZIP="$ROOT_DIR/dist/RSIAtlas-notarize.zip"
rm -f "$ZIP"
ditto -c -k --keepParent "$APP_BUNDLE" "$ZIP"
xcrun notarytool submit "$ZIP" \
  --key "$RSI_ATLAS_NOTARY_KEY" \
  --key-id "$RSI_ATLAS_NOTARY_KEY_ID" \
  --issuer "$RSI_ATLAS_NOTARY_ISSUER" \
  --wait
xcrun stapler staple "$APP_BUNDLE"
echo "signed+stapled: record Gatekeeper clean-user evidence before marking acceptance Proven"
