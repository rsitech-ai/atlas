# Contributing to RSI Atlas

Thanks for helping. Keep changes small, honest about capabilities, and fail-closed when
authority is missing.

## Prerequisites

- Apple Silicon Mac, macOS 15+
- Xcode CLT / Swift 6
- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Homebrew **PostgreSQL 17.10** and **pgvector 0.8.5** (project-owned cluster under `.local`, not the Homebrew service)

Clone anywhere; do not hard-code personal home paths in docs or scripts.

## Quick start

```bash
uv sync
./infra/local/postgres.sh start
./script/build_and_run.sh --verify
```

Development loopback TCP is the default for the engine. Native Unix-domain IPC:

```bash
./script/build_and_run.sh --release-ipc
```

## Verify before opening a PR

```bash
uv lock --check
uv run ruff check packages services infra
uv run ruff format --check packages services infra
uv run mypy packages services infra
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest -q
uv run atlas doctor --json
swift test --package-path apps/macos
swift build --package-path apps/macos --product RSIAtlas
```

Without `RSI_ATLAS_TEST_DATABASE_URL`, integration tests that need the owner-only Unix
socket will fail or skip. CI runs lint plus a DB-free unit subset; run the full suite
locally before claiming Postgres behavior.

## Optional extras

OSS dense embeddings (candidate, not sealed PRODUCTION):

```bash
uv sync --package rsi-atlas-ingestion --extra onnx
uv run python script/install_embedding_model.py --download
# then RSI_ATLAS_EMBEDDER=onnx and RSI_ATLAS_EMBEDDING_ARTIFACT_DIR=...
```

DuckDB analytics stays fail-closed unless `RSI_ATLAS_ENABLE_DUCKDB=1` and the duckdb extra
are installed.

## Commit and PR expectations

- Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`).
- Prefer one focused change per PR; update `docs/` only when behavior or governance changes.
- Do not mark acceptance criteria `Proven` without the evidence the design requires (especially signing / notarization).
- Do not add Docling, silent network downloads, or baked-in API keys.
- Never commit secrets, `.env`, notary keys, or local `.local/` data.

## Dependency governance

Governed dependency decisions live under `docs/dependency-governance/`. New runtime
dependencies need an approval record and lockfile update—not an ad-hoc `pip install`.

## Code of conduct

Participation is governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Security

See [SECURITY.md](SECURITY.md) for private reporting. Do not file public issues for
vulnerabilities that expose local documents or credentials.
