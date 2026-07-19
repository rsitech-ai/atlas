#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
APP_PROCESS="RSIAtlas"
APP_DISPLAY_NAME="RSI Atlas"
BUNDLE_ID="ai.rsitech.RSIAtlas"
MIN_SYSTEM_VERSION="15.0"
ENGINE_HOST="${RSI_ATLAS_ENGINE_HOST:-127.0.0.1}"
ENGINE_PORT="${RSI_ATLAS_ENGINE_PORT:-8765}"
ENGINE_SERVICE_LABEL="ai.rsitech.RSIAtlas.engine"
ENGINE_SERVICE_DOMAIN="gui/$(id -u)"

case "$MODE" in
  run|--debug|debug|--logs|logs|--telemetry|telemetry|--verify|verify|--release-ipc)
    ;;
  *)
    echo "usage: $0 [run|--debug|--logs|--telemetry|--verify|--release-ipc]" >&2
    exit 2
    ;;
esac

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RSI_ATLAS_DATA_ROOT="${RSI_ATLAS_DATA_ROOT:-$ROOT_DIR/.local}"
export RSI_ATLAS_DATA_ROOT
DIST_DIR="$ROOT_DIR/dist"
APP_BUNDLE="$DIST_DIR/$APP_PROCESS.app"
APP_CONTENTS="$APP_BUNDLE/Contents"
APP_MACOS="$APP_CONTENTS/MacOS"
APP_BINARY="$APP_MACOS/$APP_PROCESS"
INFO_PLIST="$APP_CONTENTS/Info.plist"
ENGINE_LOG="$DIST_DIR/engine.log"
ENGINE_STATUS_URL="http://$ENGINE_HOST:$ENGINE_PORT/v1/system/status"
POSTGRES_SCRIPT="$ROOT_DIR/infra/local/postgres.sh"
RELEASE_IPC=0
if [[ "$MODE" == "--release-ipc" ]] || [[ "${RSI_ATLAS_RELEASE_IPC:-}" == "1" ]]; then
  RELEASE_IPC=1
  export RSI_ATLAS_RELEASE_IPC=1
  unset RSI_ATLAS_ALLOW_LOOPBACK_TCP || true
  # --release-ipc still builds/runs the app after engine is up.
  if [[ "$MODE" == "--release-ipc" ]]; then
    MODE="run"
  fi
else
  # Development path: explicit loopback TCP unless caller overrides.
  export RSI_ATLAS_ALLOW_LOOPBACK_TCP="${RSI_ATLAS_ALLOW_LOOPBACK_TCP:-1}"
fi

owned_app_pids() {
  local app_pid
  local app_command
  while IFS= read -r app_pid; do
    [[ -n "$app_pid" ]] || continue
    app_command="$(ps -p "$app_pid" -o command= 2>/dev/null || true)"
    if [[ "$app_command" == "$APP_BINARY" ]]; then
      printf '%s\n' "$app_pid"
    fi
  done < <(pgrep -x "$APP_PROCESS" 2>/dev/null || true)
}

stop_owned_app() {
  local app_pid
  while IFS= read -r app_pid; do
    [[ -n "$app_pid" ]] || continue
    kill "$app_pid"
  done < <(owned_app_pids)

  local attempt
  for attempt in {1..30}; do
    if [[ -z "$(owned_app_pids)" ]]; then
      return
    fi
    sleep 0.1
  done
  echo "$APP_DISPLAY_NAME did not stop cleanly." >&2
  exit 1
}

stop_owned_engine() {
  if ! launchctl print "$ENGINE_SERVICE_DOMAIN/$ENGINE_SERVICE_LABEL" >/dev/null 2>&1; then
    return
  fi

  launchctl remove "$ENGINE_SERVICE_LABEL" >/dev/null 2>&1 || true
  local attempt
  for attempt in {1..50}; do
    if ! launchctl print "$ENGINE_SERVICE_DOMAIN/$ENGINE_SERVICE_LABEL" >/dev/null 2>&1; then
      if [[ "$RELEASE_IPC" -eq 1 ]]; then
        return
      fi
      if ! curl --fail --silent "$ENGINE_STATUS_URL" >/dev/null 2>&1; then
        return
      fi
    fi
    sleep 0.1
  done
  echo "The owned RSI Atlas Engine did not stop cleanly." >&2
  exit 1
}

wait_for_engine() {
  if [[ "$RELEASE_IPC" -eq 1 ]]; then
    if ! "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/script/wait_engine_ipc.py" \
      --timeout-seconds 8 --require-auth; then
      echo "RSI Atlas Engine did not become ready on Unix-domain IPC." >&2
      tail -n 30 "$ENGINE_LOG" >&2 || true
      exit 1
    fi
    return
  fi
  local attempt
  for attempt in {1..50}; do
    if curl --fail --silent "$ENGINE_STATUS_URL" >/dev/null 2>&1; then
      return
    fi
    sleep 0.1
  done
  echo "RSI Atlas Engine did not become ready at $ENGINE_STATUS_URL." >&2
  tail -n 30 "$ENGINE_LOG" >&2 || true
  exit 1
}

verify_engine_contract() {
  curl --fail --silent --show-error "$ENGINE_STATUS_URL" \
    | "$ROOT_DIR/.venv/bin/python" -c '
import json
import sys

expected = (
    ("engine_runtime", "engine", "healthy"),
    ("database", "storage", "healthy"),
    ("artifact_store", "storage", "healthy"),
    ("offline_policy", "privacy", "healthy"),
    ("trace_store", "observability", "healthy"),
    ("resource_policy", "resources", "healthy"),
    ("model_registry", "resources", "degraded"),
    ("contract_api", "engine", "healthy"),
)
payload = json.load(sys.stdin)
actual = tuple(
    (item.get("component_id"), item.get("group"), item.get("state"))
    for item in payload.get("components", ())
)
if payload.get("schema_version") != "1.1.0":
    raise SystemExit("unexpected runtime schema")
if payload.get("profile") != "offline" or payload.get("state") != "degraded":
    raise SystemExit("runtime baseline is not degraded-only-model")
if actual != expected or len({item[0] for item in actual}) != len(expected):
    raise SystemExit("runtime components do not match the Phase 1 contract")
'
}

wait_for_app() {
  local attempt
  for attempt in {1..30}; do
    if [[ -n "$(owned_app_pids)" ]]; then
      return
    fi
    sleep 0.1
  done
  echo "$APP_DISPLAY_NAME did not launch from $APP_BUNDLE." >&2
  exit 1
}

stage_app_bundle() {
  local build_binary
  local build_bin_path
  build_bin_path="$(swift build --package-path "$ROOT_DIR/apps/macos" --show-bin-path)"
  build_binary="$build_bin_path/$APP_PROCESS"

  rm -rf "$APP_BUNDLE"
  mkdir -p "$APP_MACOS"
  cp "$build_binary" "$APP_BINARY"
  chmod +x "$APP_BINARY"

  cat >"$INFO_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "https://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>$APP_PROCESS</string>
  <key>CFBundleIdentifier</key>
  <string>$BUNDLE_ID</string>
  <key>CFBundleName</key>
  <string>$APP_DISPLAY_NAME</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>LSMinimumSystemVersion</key>
  <string>$MIN_SYSTEM_VERSION</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
</dict>
</plist>
PLIST
}

open_app() {
  # Propagate IPC policy into the GUI process (open does not inherit shell env).
  if [[ "$RELEASE_IPC" -eq 1 ]]; then
    /usr/bin/open -n "$APP_BUNDLE" \
      --env "RSI_ATLAS_DATA_ROOT=$RSI_ATLAS_DATA_ROOT" \
      --env "RSI_ATLAS_RELEASE_IPC=1"
  else
    /usr/bin/open -n "$APP_BUNDLE" \
      --env "RSI_ATLAS_DATA_ROOT=$RSI_ATLAS_DATA_ROOT" \
      --env "RSI_ATLAS_ALLOW_LOOPBACK_TCP=${RSI_ATLAS_ALLOW_LOOPBACK_TCP:-1}" \
      --env "RSI_ATLAS_ENGINE_HOST=$ENGINE_HOST" \
      --env "RSI_ATLAS_ENGINE_PORT=$ENGINE_PORT"
  fi
}

mkdir -p "$DIST_DIR"
stop_owned_app
stop_owned_engine

if [[ "$RELEASE_IPC" -eq 0 ]] && curl --fail --silent "$ENGINE_STATUS_URL" >/dev/null 2>&1; then
  echo "Port $ENGINE_PORT already serves an unowned process; refusing to replace it." >&2
  exit 1
fi

cd "$ROOT_DIR"
uv sync --all-packages
"$POSTGRES_SCRIPT" start
if [[ "$RELEASE_IPC" -eq 1 ]]; then
  # Release IPC: authenticated Unix domain socket (criterion 114).
  launchctl submit \
    -l "$ENGINE_SERVICE_LABEL" \
    -o "$ENGINE_LOG" \
    -e "$ENGINE_LOG" \
    -- /usr/bin/env \
    "RSI_ATLAS_DATA_ROOT=$RSI_ATLAS_DATA_ROOT" \
    "RSI_ATLAS_RELEASE_IPC=1" \
    "RSI_ATLAS_IPC_AUTH=1" \
    "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/script/run_engine.py" --release-ipc
else
  # Development path: explicit loopback TCP for convenience.
  launchctl submit \
    -l "$ENGINE_SERVICE_LABEL" \
    -o "$ENGINE_LOG" \
    -e "$ENGINE_LOG" \
    -- /usr/bin/env \
    "RSI_ATLAS_DATA_ROOT=$RSI_ATLAS_DATA_ROOT" \
    "RSI_ATLAS_ALLOW_LOOPBACK_TCP=1" \
    "RSI_ATLAS_ENGINE_HOST=$ENGINE_HOST" \
    "RSI_ATLAS_ENGINE_PORT=$ENGINE_PORT" \
    "$ROOT_DIR/.venv/bin/uvicorn" rsi_atlas_engine.api:app \
    --host "$ENGINE_HOST" \
    --port "$ENGINE_PORT"
fi
wait_for_engine

swift build --package-path "$ROOT_DIR/apps/macos" --product "$APP_PROCESS"
stage_app_bundle

case "$MODE" in
  run)
    open_app
    ;;
  --debug|debug)
    if [[ "$RELEASE_IPC" -eq 1 ]]; then
      env RSI_ATLAS_DATA_ROOT="$RSI_ATLAS_DATA_ROOT" RSI_ATLAS_RELEASE_IPC=1 \
        lldb -- "$APP_BINARY"
    else
      env RSI_ATLAS_DATA_ROOT="$RSI_ATLAS_DATA_ROOT" \
        RSI_ATLAS_ALLOW_LOOPBACK_TCP="${RSI_ATLAS_ALLOW_LOOPBACK_TCP:-1}" \
        RSI_ATLAS_ENGINE_HOST="$ENGINE_HOST" \
        RSI_ATLAS_ENGINE_PORT="$ENGINE_PORT" \
        lldb -- "$APP_BINARY"
    fi
    ;;
  --logs|logs)
    open_app
    /usr/bin/log stream --info --style compact --predicate "process == \"$APP_PROCESS\""
    ;;
  --telemetry|telemetry)
    open_app
    /usr/bin/log stream --info --style compact --predicate "subsystem == \"$BUNDLE_ID\""
    ;;
  --verify|verify)
    open_app
    wait_for_app
    if [[ "$RELEASE_IPC" -eq 1 ]]; then
      "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/script/wait_engine_ipc.py" --timeout-seconds 2 --require-auth
    else
      verify_engine_contract
    fi
    launchctl print "$ENGINE_SERVICE_DOMAIN/$ENGINE_SERVICE_LABEL" >/dev/null
    echo "Verified $APP_DISPLAY_NAME and the degraded-only-model RSI Atlas Engine contract."
    ;;
  *)
    echo "usage: $0 [run|--debug|--logs|--telemetry|--verify|--release-ipc]" >&2
    exit 2
    ;;
esac
