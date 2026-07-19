# RSI Atlas

RSI Atlas is a local-first crypto intelligence and research operating system for evidence-backed, reproducible analysis on Apple Silicon Macs.

The approved product and system design is in [`docs/superpowers/specs/2026-07-18-rsi-atlas-design.md`](docs/superpowers/specs/2026-07-18-rsi-atlas-design.md). The first implementation plan is in [`docs/superpowers/plans/2026-07-18-foundation-runtime-status.md`](docs/superpowers/plans/2026-07-18-foundation-runtime-status.md).

## Current slice

The repository completes the reviewed Phase 1 durable local-runtime seam, Phase 2A secure
document-admission checkpoint, Phase 2B development-qualified Tier-0 canonical PDF evidence,
Phase 2C development five-chunker slice, and Phase 2D development dense/lexical index
publication:

- strict, versioned Python runtime-status contracts;
- an immutable, content-addressed artifact store with integrity verification;
- PostgreSQL 17 persistence with data checksums over an owner-only Unix socket and hash-locked migrations;
- a pgvector-enabled foundation schema with tenant/workspace authorization and actor/trace provenance;
- metadata-only owner-private local traces, enforced offline process policy, resource admission,
  and a model registry with an honest unavailable provider;
- real dependency-injected runtime diagnostics with exact component/group contracts and typed
  remediation;
- `atlas doctor` and `GET /v1/system/status` on loopback only;
- a native SwiftUI Command Center with grouped live evidence, stale-state preservation, fault
  remediation, multi-window behavior, keyboard refresh, and accessibility identifiers;
- strict cross-language acquisition, safety-profile, admission-decision, and durable-record
  contracts;
- bounded raw PDF streaming into owner-private staging and immutable content-addressed storage,
  followed by append-only PostgreSQL acquisition, decision, duplicate-link, and outbox evidence;
- a conservative admission policy that can quarantine, reject unsafe input, or link an exact
  same-workspace duplicate, but can never silently promote a document;
- native and CLI import boundaries with stable acquisition/trace identity, idempotent retry,
  hard-kill orphan recovery, strict response binding, and no remote fallback;
- a native Evidence destination showing truthful empty, progress, review, rejected, duplicate,
  failure, and retry states with accessible identifiers;
- governed Tier-0 PDF parser dependency approval (`pypdf` / `pdfminer.six`); Docling stays blocked;
- an isolated Seatbelt document worker for preflight and development-qualified parse;
- preflight assessment before parse, with Process PDF / `processing:start` gated off
  encrypted, rejected, duplicate, and embedded-file paths;
- append-only parser-attempt journals, CAS-first canonical JSON, and canonical page inspection via
  loopback processing APIs plus the native Evidence inspector;
- five implemented chunking families (`fixed_token`, `recursive`, `page_based`, `parent_child`,
  `table_aware`) with frozen intrinsic goldens, CAS-first chunk-set persistence, and loopback
  chunk inspect APIs (`chunking:start`, list, get);
- development fixture embeddings (stdlib hash→vector) plus governed offline OSS
  `oss_token_hash_v1` candidate embedder and fail-closed optional ONNX artifact path
  (`script/install_embedding_model.py`; opt-in `--download` only, pinned MiniLM
  URL+sha256 in governance; no silent download); lexical overlap post-RRF
  rerank (stdlib); fixture remains the default for tests;
  migration `0008` staging dense pgvector + PostgreSQL FTS lexical + exact-identifier rows,
  atomic publication activate/rollback via an active pointer, and loopback
  `indexing:start` / index-version list / `publication:activate` /
  `publication:rollback` APIs. Staging stays non-searchable until activation;
- Phase 3 hybrid retrieval: active-only dense/lexical/exact candidate generation,
  intent-weighted RRF + lexical rerank, coverage/abstention,
  Document Evidence specialist (extractive, no LLM), assertion→citation→report draft gate,
  immutable review events, Postgres-durable linear workflow interrupt/resume
  (migration `0012`; no LangGraph), migration `0009`, and loopback
  `research:retrieve` / `specialist:document` / `reports:draft` / review /
  `research/workflows:*` APIs;
- Phase 4 multi-chain / quantitative: offline Bitcoin/EVM/Solana/market/governance/GitHub
  fixtures; optional monitored live HTTPS collect behind user-supplied allowlisted origins
  (deny-by-default NetworkPolicy; no baked-in API keys); optional DuckDB/Parquet analytics
  when `RSI_ATLAS_ENABLE_DUCKDB=1` + duckdb install; otherwise fail-closed; loopback
  `collectors:import-fixture` / observations list APIs;
- Phase 5 monitoring / comparison: deterministic change detection before
  semantic triage, rule matching (threshold / rate-of-change / finality / quality),
  materiality screen, alert dedup + append-only lifecycle, research invalidation,
  targeted research launch (plan validation; linear workflow available), comparison matrix /
  cross-chain timeline payloads with envelope links, migration `0011`, and loopback
  monitoring APIs. Semantic triage stays `blocked_semantic_triage`;
- Phase 6 engineering / release maturity: offline evaluation harness; Codex sanitize/gate;
  filesystem backup/restore + optional owner file-key AES-GCM encryption (Keychain still
  blocked); Safe Mode; integrity scrub; SBOM from `uv.lock`; entitlement-matrix draft;
  fail-closed `script/release_check.py`; loopback Phase 6 APIs;
- native sidebar destinations for Command Center, Evidence, Research Canvas, Comparison,
  and Chunk Inspector bound to loopback workflow / timeline / chunk-inspect clients
  (minimal but real; not Report Studio polish).

Docling stays blocked. System Tesseract OCR is fail-closed when absent. Sealed-holdout
`PRODUCTION` embedding promotion, neural cross-encoder, calibrated judges/semantic triage,
WebSocket collectors, LangGraph, XPC, Apple Developer ID signing, notarization, stapling,
embedded signed Python, and Section 33 criterion closure remain open. Hybrid retrieval,
cited reports, collectors, monitoring, eval, and backup are production-local OSS
capabilities with tests—not automatic criterion `Proven` without release-artifact proof.
Parent-child/table-aware remain development-only. Signing/notarization stay blocked on
owner certs/secrets. MiniLM ONNX install is opt-in (`script/install_embedding_model.py
--download` with pinned URL+sha256); runtime `OfflineOnnxEmbedder` stays fail-closed and
string-input-only until tokenizer wiring lands—prefer `oss_token_hash_v1` for production-local dense.

## Requirements

- Apple Silicon Mac running macOS 15 or newer
- Xcode command-line tools with Swift 6
- Python 3.11 or newer
- [uv](https://docs.astral.sh/uv/)
- Homebrew PostgreSQL 17.10 and pgvector 0.8.5

## Run

```bash
./script/build_and_run.sh --verify
```

This syncs the pinned Python workspace, starts the project-owned PostgreSQL cluster under `.local`
on an owner-only Unix socket, passes that exact data root into the launchd-owned engine on
`127.0.0.1:8765`, builds `RSIAtlas`, stages `dist/RSIAtlas.app`, launches it, and verifies schema
`1.1.0` plus the exact degraded-only-model eight-component contract.

The local database never uses the Homebrew service or its default cluster:

```bash
./infra/local/postgres.sh start
./infra/local/postgres.sh status
./infra/local/postgres.sh stop
```

Override `RSI_ATLAS_DATA_ROOT` to place the development cluster outside the repository. The PostgreSQL root, data directory, and socket directory are restricted to the current user.

## Verify

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

The product is research-only. It has no trading, wallet, signing, custody, or private-key authority.
