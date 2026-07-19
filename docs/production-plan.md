# Production Plan: RSI Atlas

## Product Brief

- Target user: an individual quantitative crypto researcher first; a small crypto hedge-fund research team second.
- Primary job: turn local and explicitly collected crypto evidence into reproducible, inspectable research.
- Core workflow: acquire evidence, investigate a material question, inspect lineage, and publish a
  cited result. The current checkpoint implements local runtime readiness plus raw, durable,
  fail-closed PDF admission only.
- Business model: a professional research workstation; commercialization is outside the foundation slice.
- Supported macOS versions: macOS 15 or newer on Apple Silicon; the reference hardware has 24–36 GB unified memory.
- Offline behavior: strict offline is the default. The current engine exposes a development endpoint only on `127.0.0.1` and enables no remote collector, model, telemetry exporter, update check, or remote resource.
- Data handled: runtime health metadata plus explicitly selected local PDF bytes, their SHA-256
  identity, strict safety/admission evidence, workspace/actor/trace context, and append-only history.
  No parser, embedding, prompt, or model receives document bytes in this checkpoint.
- Privacy posture: zero egress for private data, prompts, embeddings, traces, reports, and evaluations.
- V1 scope: the approved design in `docs/superpowers/specs/2026-07-18-rsi-atlas-design.md`, delivered through independently verifiable vertical slices.
- Explicitly out of scope for this checkpoint: promoted PDF profiling, parsing/OCR,
  canonicalization, chunking/indexing, retrieval, qualified model execution, collectors, LangGraph,
  report generation, XPC, signing, notarization, updates, backup, and release recovery.

## Architecture

- Scene model: SwiftUI `WindowGroup` with a foreground native app lifecycle.
- Window roles: independent Command Center windows are supported; specialist and auxiliary window
  roles are not implemented.
- Layout model: native sidebar/detail `NavigationSplitView` with live Command Center and Evidence
  destinations.
- State ownership: scene-owned `CommandCenterStore` and `DocumentImportStore`; both use
  latest-request-wins behavior, explicit loading/failure states, and retry without fabricated
  evidence.
- Persistence: immutable content-addressed artifacts, hash-locked PostgreSQL migrations, pgvector,
  append-only acquisition/decision/duplicate/outbox evidence, and metadata-only trace JSONL persist
  below an exact owner-private data root.
- Services: typed Swift loopback clients consume `GET /v1/system/status` and file-backed
  `POST .../documents:admit`; Python shares runtime probes with `atlas doctor` and exposes a direct
  owner-private `atlas import-pdf` CLI boundary.
- App Intents / Foundation Models / advanced capabilities: not enabled.
- Folder/module structure: Swift contract/client/store code is separated from SwiftUI; Python contracts are separated from deterministic services and transport adapters.

## Build And Run

- Project type: Python uv workspace plus a SwiftPM macOS GUI executable.
- Build command: `swift build --package-path apps/macos --product RSIAtlas`.
- Run command: `./script/build_and_run.sh`.
- `script/build_and_run.sh` status: implemented with an explicitly labeled per-user `launchctl` engine job, loopback readiness checks, `.app` staging, foreground launch, and canonical debug/log/telemetry/verify modes.
- Codex Run action status: `.codex/environments/environment.toml` points to the project-local script.

## Design System

- Apple Design Resources checked: not required for this native foundation shell; current visual-kit claims remain unverified.
- Platform UI kit/version: system SwiftUI controls on macOS 15+.
- SF Symbols/Icon Composer status: system SF Symbols are used; custom icon work is not started.
- Native structures: `WindowGroup`, `NavigationSplitView`, sidebar list, toolbar, keyboard shortcut, progress, list sections, and `ContentUnavailableView`.
- Adaptive states: runtime loading/healthy/failure and Evidence empty/uploading/awaiting-review/
  rejected/duplicate/failure states are implemented. Password presentation is contract-tested for a
  future authoritative profiler but runtime-unreachable in Phase 2A; encrypted markers remain
  unknown and quarantined. Parsed research, retrieval, report, and long-data states remain outside
  this checkpoint.
- Visual style: restrained native graphite/system surfaces with semantic status accents; no custom chrome or decorative animation.
- Motion rules: no decorative motion; system progress behavior only.
- Accessibility requirements: semantic labels and identifiers, separate remediation rows, keyboard
  refresh, VoiceOver-order accessibility-tree proof, system text/colors, compact-window scrolling,
  Light/Dark, increased contrast, large text, Reduce Motion, and multi-window behavior are verified
  in the development app. Debug-only QA overrides do not change release behavior.

## Test Strategy

- Unit tests: 827 PostgreSQL-configured Python tests and 43 Swift tests cover Phase 1 plus strict
  acquisition/admission contracts, bounded streaming and responses, immutable raw publication,
  append-only persistence, duplicate/concurrency/replay isolation, hard-kill staging recovery,
  latest-request permutations, transport cancellation, and native accessibility presentation.
- Integration tests or mocks: real PostgreSQL 17.10/pgvector 0.8.5 integration runs alongside
  FastAPI `TestClient`; Swift injects a real data-loading boundary and decodes the shared fixture.
- UI/manual smoke: expected degraded-only-model baseline; PostgreSQL/engine fault recovery; clean,
  malformed, rejected-signature, encrypted-marker, and exact-duplicate imports; same-request retry;
  truthful raw hash and quarantine copy; keyboard and VoiceOver order; 1120×760 and 860×600 content
  layouts; Light/Dark, increased contrast, large text, Reduce Motion, and a second window.
- Release smoke: not in scope; the staged app is an unsigned local debug artifact.
- Commands: `uv lock --check`, `uv run ruff check packages services infra`,
  `uv run ruff format --check packages services infra`, `uv run mypy packages services infra`,
  `RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest -q`,
  `swift test --package-path apps/macos`, debug/release Swift product builds, and
  `./script/build_and_run.sh --verify` when the host resource probe is nominal.

## Observability

- Logger subsystem: metadata-only OpenTelemetry spans persist to owner-private local JSONL; remote
  exporters are absent in offline mode. `ai.rsitech.RSIAtlas` remains reserved for later unified logs.
- Categories: runtime lifecycle, trace context, and user refresh are the current categories.
- Key lifecycle/action events: engine startup/readiness, app process readiness, migration state,
  artifact integrity, trace flush, resource admission, and model unavailability are inspectable.
- Sensitive logging exclusions: no document content, prompt, credential, secret, analyst note, report, or private path contents may be logged.

## Distribution Readiness

- Bundle ID: `ai.rsitech.RSIAtlas` for the local staged bundle.
- Signing team: unconfigured.
- Sandbox/entitlements: unconfigured; release capability work remains blocked on a reviewed process matrix.
- Privacy manifest: not created because this slice is not a release candidate.
- Privacy disclosures: not prepared.
- Assets: no custom app icon, screenshots, or marketing assets.
- Metadata: not prepared.
- Review notes: not applicable; the approved design selects Developer ID distribution outside the Mac App Store.
- Known blockers: embedded Python, local PostgreSQL packaging, XPC/Unix-socket release transport, sandbox/hardened runtime, nested signing, notarization (needs Apple secrets), entitlement matrix, clean install, upgrade, rollback; Keychain-wrapped backup keys. Development SBOM + fail-closed unsigned release checks and filesystem backup/Safe Mode exist but are not release evidence.

## Iteration Log

| Date | Gate | Change | Verification | Next blocker |
| --- | --- | --- | --- | --- |
| 2026-07-18 | Foundation contract | Added strict Python and Swift status contracts, deterministic diagnostics, CLI, and loopback API. | Final gate: 11 Python tests, 8 Swift tests, Ruff, strict mypy, uv lock check, and Swift product build passed. | Add persistence and artifact-store diagnostics in a separate slice. |
| 2026-07-18 | Native shell | Added a native sidebar/detail Command Center with loading, healthy, failure, retry, and keyboard refresh behavior. | Foreground accessibility and visual inspection proved healthy state, engine-down state via `⌘R`, and same-window recovery through Retry. | Minimum-window drag could not be established through the current UI-control surface; compact layout remains unverified. |
| 2026-07-18 | Runtime lifecycle | Replaced shell-owned background execution with an explicitly labeled per-user `launchctl` job and condition-based shutdown. | A separate shell confirmed the engine remained `running` and returned the healthy 3-component contract after `build_and_run.sh --verify` exited. | Replace development loopback transport with authenticated release IPC in a separate security milestone. |
| 2026-07-18 | Independent review | Hardened exact app-process ownership, pre-side-effect mode validation, latest-request-wins refresh, and non-empty diagnostics. | Reviewer re-check found all four findings resolved with no new Critical or Important regression. | Complete real-probe Task 6 and its foreground/fault acceptance matrix. |
| 2026-07-18 | Phase 1 durable runtime | Connected the native Command Center to exact real probes for PostgreSQL/pgvector, immutable artifacts, offline policy, local traces, resources, models, and contract/API truth. | 660 Python and 21 Swift tests; Ruff/format/mypy/lock/build gates; disposable PostgreSQL/artifact/engine fault recovery; persistence; process/socket proof; development `atlas doctor` zero-egress; foreground compact, appearance, accessibility, and multi-window passes. Independent source review approved `7864630` and the QA delta through `647c25b` with no Critical/Important findings. | Phase 2 document-intelligence admission/import plan; release IPC, signing, backup/restore, and exact release-artifact zero egress remain later gates. |
| 2026-07-19 | Phase 2A secure admission | Added strict native/Python admission contracts, bounded file-backed upload, raw-first immutable publication, conservative decisions, append-only acquisition history, exact-duplicate isolation, and the native Evidence destination. | 827 Python and 43 Swift tests; hard engine kill and orphan recovery; PostgreSQL-down raw retention and same-ID retry; byte/record persistence across full restart; live API/direct-CLI coexistence; adversarial boundary matrix; foreground import/accessibility/appearance/multi-window proof; independent reviews found no remaining Critical/Important findings through `113110c`. | Phase 2B promoted parser/preflight/canonical-page evidence; release IPC/signing/backup remain later gates. |
| 2026-07-19 | Phase 2B Tier-0 canonical evidence | Added governed PDF parser dependency approval, Seatbelt document worker, preflight/parse attempt journals, development-qualified `pypdf` parse, CAS-first canonical pages, processing API, and Evidence inspector page view. Docling remains blocked; no production promotion. | 935 Python and 44 Swift tests; ruff/mypy/lock; Seatbelt worker + dependency governance; canonical persistence/idempotency/corruption; processing API contract tests; Swift decode + debug/release builds; `build_and_run.sh --verify`. | Phase 2C chunking; Docling/OCR; sealed holdout production promotion; release IPC/signing/backup. |
| 2026-07-19 | Phase 2B re-review remediation | Cleared Important review blockers through `6383861`: preflight-before-parse, Process PDF admission/assessment gate, Keychain Seatbelt Mach canary, honest Task 8/9 evidence language. Independent re-review: approve-with-nits. | Focused remediation: Seatbelt Keychain canary, processing-pipeline/preflight/API tests, Swift EvidencePresentationTests. | Phase 2C five chunkers + inspect APIs; Docling remains blocked. |
| 2026-07-19 | Phase 2C five chunkers (dev) | Added chunk contracts + full §13.2 registry, five implemented families, frozen intrinsic goldens, migration `0007`, CAS-first chunk-set persistence, and loopback chunk inspect APIs. No embeddings/indexes/publication. Docling untouched. | **973** Python and **44** Swift tests; ruff/mypy/lock; chunk contract/unit/benchmark/persistence/API tests. | Phase 2D dense/lexical indexes + atomic publication; criterion 15 production-ready parent-child/table; sealed holdout; native chunk inspector UI optional. |
| 2026-07-19 | Phase 2D indexes + atomic publication (dev) | Added retrieval publication contracts (`INDEX_VALIDATED`/`PUBLISHED`), fixture-only deterministic embeddings (production embedding models blocked), migration `0008` staging dense pgvector + FTS lexical + exact-identifier rows, atomic activate/rollback active pointer, and loopback `indexing:start` / index-version list / `publication:activate` / `publication:rollback` APIs. Staging remains non-searchable until activation. Docling untouched. Mid-txn abort injection deferred. | Focused indexing/publication/API green; full suite **990** collected (known intermittent symlink-ancestor postgres harness EBADF under load); **44** Swift; ruff/mypy/lock. Tip through rollback API commit. | Phase 3 hybrid retrieval plan; production embedding promotion; criterion 15; OCR/parser promotion; interrupt/resume; Tantivy optional after benchmark. |
| 2026-07-19 | Phase 3 hybrid retrieval / research (dev) | Added retrieval/research/report contracts; active-only dense+lexical+exact hybrid search; intent-weighted RRF EvidencePacket with coverage/abstention + replay; Document Evidence specialist; assertion→citation→report draft gate; immutable review; migration `0009`; loopback research APIs. Fixture embeddings only; Docling/production embeddings/rerankers/LangGraph blocked. | **1009** Python and **44** Swift tests; ruff/mypy/lock; dependency-governance baseline refreshed for new workspace packages. | Production embedding + cross-encoder governance; LangGraph interrupt/resume; remaining specialists; calibrated judges; native Research Canvas/Report Studio; Phase 4 multi-chain planes; criteria 4–8/25–60 remain open. |
| 2026-07-19 | Phase 4 multi-chain / quantitative (dev) | Added observation/collector contracts; offline Bitcoin/EVM/Solana/market/governance/GitHub fixtures; raw envelopes before normalize; bitemporal observation persistence (`0010`); quarantine; reorg orphan stub; leakage-safe features; non-trading signals; fail-closed live + DuckDB/Parquet stubs; loopback `collectors:import-fixture` / observations list. No live RPC/WebSocket. | **1048** Python and **44** Swift tests; ruff/mypy/lock; dependency-governance baseline refreshed for collectors package. | Live providers; DuckDB/Parquet governance; full detector roster; criteria 43–44/61–81 remain open; Phase 5 monitoring. |
| 2026-07-19 | Phase 5 monitoring / comparison (dev) | Added monitoring/comparison contracts; deterministic detectors + rule matcher + materiality screen; alert dedup + append-only lifecycle; research invalidation; targeted research launch stub (no LangGraph); comparison matrix / cross-chain timeline with envelope links; fail-closed semantic triage; migration `0011`; loopback monitoring APIs. | **1077** Python collected / focused Phase 5 suite green; **44** Swift unchanged; ruff/mypy. | Calibrated semantic triage; LangGraph monitoring-driven research; native timeline/matrix UI; criteria 45/61/82–84 remain open; Phase 6 eval/release. |
| 2026-07-19 | Phase 6 engineering / release maturity (dev) | Added evaluation/Codex/recovery/release contracts; offline eval harness + frozen fixture + fail-closed judges; Codex sanitize/approval/patch gate with authority denial; filesystem backup/restore/Safe Mode/scrub; SBOM from `uv.lock`; fail-closed unsigned release checks; loopback Phase 6 APIs. | **1124** Python collected / focused Phase 6 suite **47** green; ruff/mypy. | Apple Developer ID signing, notarization, stapling, Gatekeeper clean-user, Keychain-wrapped backups, embedded signed Python, calibrated judges, live Codex App Server; criteria 85–134 remain open. |
| 2026-07-19 | OSS production-local promotion | Governed offline OSS embeddings (`oss_token_hash_v1` + fail-closed ONNX install), lexical rerank, linear workflow interrupt/resume (no LangGraph), optional monitored live HTTPS collectors, optional DuckDB/Parquet, system Tesseract OCR fail-closed, file-key AES-GCM backup, release entitlement matrix + SBOM write, native Research/Comparison/Chunks shells. Docling stays blocked; criteria remain Not proven; signing/notarization blocked on secrets. | Focused OSS tests green; Swift **44**; ruff/mypy on touched packages. | Install ONNX artifact for semantic embeddings; enable DuckDB optionally; provide Apple signing/notary secrets; Postgres-durable workflow; bind native timeline/research clients; sealed holdout PRODUCTION promotion. |
| 2026-07-19 | MiniLM ONNX embedder path | Stdlib BERT WordPiece + mean-pool `OfflineOnnxEmbedder`; install pins ONNX+vocab (fixed tip commit); optional `onnxruntime` extra governed; docs honesty. Still candidate, not sealed PRODUCTION. | Focused WordPiece/install tests green; optional e2e skip-if-artifact-missing. | Owner `--download` + `[onnx]` extra; sealed holdout PRODUCTION promotion. |
