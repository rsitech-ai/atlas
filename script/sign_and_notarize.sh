#!/usr/bin/env bash
# Fail-closed Developer ID sign + notarize. Requires a complete runtime and Apple secrets.
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_BUNDLE="${1:-$ROOT_DIR/dist/RSIAtlas.app}"
EXPECTED_TEAM_ID="${RSI_ATLAS_EXPECTED_TEAM_ID:-2NY8A789TN}"

if [[ ! -d "$APP_BUNDLE" ]]; then
  echo "missing app bundle: $APP_BUNDLE" >&2
  exit 1
fi
if ! uv run python "$ROOT_DIR/script/check_release_runtime.py" --bundle "$APP_BUNDLE"; then
  echo "embedded runtime is incomplete; refusing to modify signatures" >&2
  exit 3
fi
if [[ -z "${RSI_ATLAS_SIGNING_IDENTITY:-}" ]]; then
  echo "RSI_ATLAS_SIGNING_IDENTITY is required; see docs/release/signing-notarization-blockers.md" >&2
  exit 2
fi
if [[ -z "${RSI_ATLAS_NOTARY_KEY:-}" || -z "${RSI_ATLAS_NOTARY_KEY_ID:-}" || -z "${RSI_ATLAS_NOTARY_ISSUER:-}" ]]; then
  echo "notary env (RSI_ATLAS_NOTARY_KEY/KEY_ID/ISSUER) required; refusing unsigned notarization claim" >&2
  exit 2
fi
if ! security find-identity -v -p codesigning | grep -F "$RSI_ATLAS_SIGNING_IDENTITY" >/dev/null; then
  echo "requested signing identity is not installed with a usable private key" >&2
  exit 2
fi

verify_team() {
  local signed_path="$1"
  local actual_team
  actual_team="$(codesign -d --verbose=4 "$signed_path" 2>&1 | sed -n 's/^TeamIdentifier=//p')"
  if [[ "$actual_team" != "$EXPECTED_TEAM_ID" ]]; then
    echo "unexpected TeamIdentifier for $signed_path: ${actual_team:-missing}" >&2
    exit 4
  fi
}

sign_code() {
  local code_path="$1"
  codesign --force --options runtime --timestamp --sign "$RSI_ATLAS_SIGNING_IDENTITY" "$code_path"
  codesign --verify --strict "$code_path"
  verify_team "$code_path"
}

echo "signing nested Mach-O code inside-out with Developer ID…"
SIGNED_MACH_O=0
while IFS= read -r -d '' candidate; do
  if file -b "$candidate" | grep -q 'Mach-O'; then
    sign_code "$candidate"
    SIGNED_MACH_O=$((SIGNED_MACH_O + 1))
  fi
done < <(find "$APP_BUNDLE/Contents" -depth -type f -print0)
if [[ "$SIGNED_MACH_O" -eq 0 ]]; then
  echo "no Mach-O code found in bundle" >&2
  exit 4
fi

while IFS= read -r -d '' nested_bundle; do
  sign_code "$nested_bundle"
done < <(
  find "$APP_BUNDLE/Contents" -depth -type d \
    \( -name '*.framework' -o -name '*.xpc' -o -name '*.appex' -o -name '*.app' \) -print0
)

sign_code "$APP_BUNDLE"
codesign --verify --strict --verbose=4 "$APP_BUNDLE"

DIST_DIR="$ROOT_DIR/dist"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP_BUNDLE/Contents/Info.plist")"
NOTARY_DIR="$(mktemp -d "$DIST_DIR/.notary.XXXXXX")"
trap 'rm -rf "$NOTARY_DIR"' EXIT
NOTARY_ARCHIVE="$NOTARY_DIR/RSIAtlas-notarize.zip"
NOTARY_LOG="$DIST_DIR/RSIAtlas-$VERSION-notary.json"
ditto -c -k --keepParent "$APP_BUNDLE" "$NOTARY_ARCHIVE"
xcrun notarytool submit "$NOTARY_ARCHIVE" \
  --key "$RSI_ATLAS_NOTARY_KEY" \
  --key-id "$RSI_ATLAS_NOTARY_KEY_ID" \
  --issuer "$RSI_ATLAS_NOTARY_ISSUER" \
  --wait \
  --output-format json >"$NOTARY_LOG"
uv run python - "$NOTARY_LOG" <<'PY'
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload.get("status") != "Accepted":
    raise SystemExit(f"notarization status is {payload.get('status')!r}, expected 'Accepted'")
PY
xcrun stapler staple "$APP_BUNDLE"
xcrun stapler validate "$APP_BUNDLE"
codesign --verify --strict --verbose=4 "$APP_BUNDLE"
verify_team "$APP_BUNDLE"
spctl --assess --type execute --verbose=4 "$APP_BUNDLE"

FINAL_ARCHIVE="$DIST_DIR/RSIAtlas-$VERSION-macOS.zip"
FINAL_ARCHIVE_TEMP="$NOTARY_DIR/$(basename "$FINAL_ARCHIVE")"
ditto -c -k --keepParent "$APP_BUNDLE" "$FINAL_ARCHIVE_TEMP"
mv -f "$FINAL_ARCHIVE_TEMP" "$FINAL_ARCHIVE"
shasum -a 256 "$FINAL_ARCHIVE" >"$FINAL_ARCHIVE.sha256"
echo "signed, notarized, stapled, and archived: $FINAL_ARCHIVE"
echo "clean-user launch proof is still required before release publication"
