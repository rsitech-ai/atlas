#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$ROOT_DIR"

# Automated repository evidence only: passing does not authorize merge or push.
# Human review and every authority decision remain outside this script.
uv lock --check
uv run ruff check packages services infra script tests
uv run ruff format --check packages services infra script tests
uv run mypy packages services infra
uv run python script/audit_pdf_parser_dependencies.py verify
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest -q
swift test --package-path apps/macos
swift build --package-path apps/macos --product RSIAtlas
