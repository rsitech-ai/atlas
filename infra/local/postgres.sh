#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_PATH="$ROOT_DIR/infra/local/postgres.sh"
SECURE_PATH_HELPER="$ROOT_DIR/infra/local/secure_path.py"
POSTGRES_PREFIX="/opt/homebrew/opt/postgresql@17"
POSTGRES_BIN="$POSTGRES_PREFIX/bin"
PG_CTL="$POSTGRES_BIN/pg_ctl"
INITDB="$POSTGRES_BIN/initdb"
CREATEDB="$POSTGRES_BIN/createdb"
PSQL="$POSTGRES_BIN/psql"
PG_CONTROLDATA="$POSTGRES_BIN/pg_controldata"
DATABASE_USER="atlas"
DATABASE_NAME="atlas"
BOUND_MODE=0

if [[ "${1:-}" == "--bound" ]]; then
  BOUND_MODE=1
  COMMAND="${2:-}"
  [[ "${RSI_ATLAS_BOUND_POSTGRES:-}" == "1" ]] || {
    echo "Internal PostgreSQL lifecycle requires a securely bound directory." >&2
    exit 1
  }
  bound_identity="$(stat -f '%d:%i' .)"
  expected_identity="${RSI_ATLAS_BOUND_DEVICE:-}:${RSI_ATLAS_BOUND_INODE:-}"
  [[ "$bound_identity" == "$expected_identity" ]] || {
    echo "Bound PostgreSQL directory identity changed." >&2
    exit 1
  }
  POSTGRES_ROOT="$(pwd -P)"
  DATA_DIRECTORY="data"
  SOCKET_DIRECTORY="$POSTGRES_ROOT/socket"
  LOG_FILE="postgres.log"
else
  COMMAND="${1:-}"
  DATA_ROOT="${RSI_ATLAS_DATA_ROOT:-$ROOT_DIR/.local}"
fi

usage() {
  echo "usage: $0 {start|stop|restart|status|test-url}" >&2
  exit 2
}

require_toolchain() {
  [[ -x "$PG_CTL" && -x "$INITDB" && -x "$CREATEDB" && -x "$PSQL" && -x "$PG_CONTROLDATA" ]] || {
    echo "PostgreSQL 17 Homebrew toolchain is missing at $POSTGRES_BIN." >&2
    exit 1
  }
  case "$($POSTGRES_BIN/postgres --version)" in
    "postgres (PostgreSQL) 17.10"*) ;;
    *)
      echo "Expected PostgreSQL 17.10 from $POSTGRES_BIN." >&2
      exit 1
      ;;
  esac
}

initialize_cluster() {
  if [[ -f "$DATA_DIRECTORY/PG_VERSION" ]]; then
    return
  fi
  "$INITDB" --pgdata="$DATA_DIRECTORY" --username="$DATABASE_USER" \
    --auth-local=trust --auth-host=reject --encoding=UTF8 --no-locale \
    --data-checksums >/dev/null
  chmod 0700 "$DATA_DIRECTORY"
}

validate_cluster() {
  local checksum_version
  checksum_version="$($PG_CONTROLDATA "$DATA_DIRECTORY" \
    | awk -F: '/Data page checksum version/ {gsub(/^[[:space:]]+/, "", $2); print $2}')"
  if [[ -z "$checksum_version" || "$checksum_version" == "0" ]]; then
    echo "PostgreSQL data checksums must be enabled before startup." >&2
    exit 1
  fi
}

server_options() {
  printf -- "-c listen_addresses='' -c unix_socket_directories='%s' -c unix_socket_permissions=0700" \
    "$SOCKET_DIRECTORY"
}

is_running() {
  "$PG_CTL" --pgdata="$DATA_DIRECTORY" status >/dev/null 2>&1
}

run_psql() (
  unset PGSERVICE PGSERVICEFILE PGHOSTADDR PGHOST PGPORT
  PGPORT=5432 "$PSQL" "$@"
)

run_createdb() (
  unset PGSERVICE PGSERVICEFILE PGHOSTADDR PGHOST PGPORT
  PGPORT=5432 "$CREATEDB" "$@"
)

start_server() {
  require_toolchain
  initialize_cluster
  validate_cluster
  if ! is_running; then
    "$PG_CTL" --pgdata="$DATA_DIRECTORY" --log="$LOG_FILE" \
      --options="$(server_options)" --wait start >/dev/null
  fi
  if ! run_psql --host="$SOCKET_DIRECTORY" --username="$DATABASE_USER" --dbname=postgres \
    --tuples-only --no-align --command="SELECT 1 FROM pg_database WHERE datname = '$DATABASE_NAME'" \
    | grep -qx 1; then
    run_createdb --host="$SOCKET_DIRECTORY" --username="$DATABASE_USER" "$DATABASE_NAME"
  fi
}

stop_server() {
  require_toolchain
  if [[ -f "$DATA_DIRECTORY/PG_VERSION" ]] && is_running; then
    "$PG_CTL" --pgdata="$DATA_DIRECTORY" --mode=fast --wait stop >/dev/null
  fi
}

case "$COMMAND" in
  start|stop|restart|status|test-url)
    ;;
  *)
    usage
    ;;
esac

if [[ "$BOUND_MODE" == 0 ]]; then
  case "$DATA_ROOT" in
    /*) ;;
    *)
      echo "RSI_ATLAS_DATA_ROOT must be an absolute path." >&2
      exit 2
      ;;
  esac
  case "$DATA_ROOT" in
    *"'"*|*$'\n'*)
      echo "RSI_ATLAS_DATA_ROOT contains unsupported characters." >&2
      exit 2
      ;;
  esac
  bind_mode="prepare"
  if [[ "$COMMAND" == "stop" || "$COMMAND" == "status" ]]; then
    bind_mode="inspect"
  fi
  bound_status=0
  /usr/bin/python3 "$SECURE_PATH_HELPER" exec "$bind_mode" "$DATA_ROOT" -- \
    "$SCRIPT_PATH" --bound "$COMMAND" || bound_status=$?
  if [[ "$COMMAND" == "stop" && "$bound_status" == 3 ]]; then
    exit 0
  fi
  exit "$bound_status"
fi

case "$COMMAND" in
  start)
    start_server
    ;;
  stop)
    stop_server
    ;;
  restart)
    stop_server
    start_server
    ;;
  status)
    require_toolchain
    is_running
    ;;
  test-url)
    printf "host='%s' user='%s' dbname='%s'\n" \
      "$SOCKET_DIRECTORY" "$DATABASE_USER" "$DATABASE_NAME"
    ;;
esac
