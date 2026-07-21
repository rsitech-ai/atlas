# Production Plan: RSI Atlas

## Product Brief

- Target user: an individual quantitative crypto researcher first; a small crypto hedge-fund research team second.
- Primary job: turn local and explicitly collected crypto evidence into reproducible, inspectable research.
- Core workflow: acquire evidence, investigate a material question, inspect lineage, and produce a
  cited draft for human review. The exact-head development state is development-complete and partially
  runtime-proven; it is not production, package, signing, notarization, or clean-install proof.
- Business model: a professional research workstation; commercialization is outside the foundation slice.
- Supported macOS versions: macOS 15 or newer on Apple Silicon; the reference hardware has 24–36 GB unified memory.
- Offline behavior: Strict Offline is the default; authenticated Unix-domain IPC is the native
  default. Development loopback TCP requires `RSI_ATLAS_ALLOW_LOOPBACK_TCP=1`; monitored HTTPS
  collection requires an explicit allowlist. No remote model, telemetry exporter, or update check
  is enabled by default.
- Data handled: runtime health metadata; explicitly selected local PDF bytes and their SHA-256
  identity; safety/admission, derivation, chunk, index, retrieval, workspace/actor/trace, and
  append-only history. Development implementations remain governed and fail closed where their
  production evidence is not sealed.
- Privacy posture: zero egress for private data, prompts, embeddings, traces, reports, and evaluations.
- V1 scope: the approved design in `docs/superpowers/specs/2026-07-18-rsi-atlas-design.md`, delivered through independently verifiable vertical slices.
- Explicitly out of scope for production readiness: owner-sealed parser/model/evaluation promotion,
  production OCR and reranking, calibrated judges, live provider qualification, complete native
  research surfaces, signed embedded runtime packaging, Developer ID signing, notarization,
  Gatekeeper clean-install, and release recovery proof.

## Architecture

- Scene model: SwiftUI `WindowGroup` with a foreground native app lifecycle.
- Window roles: independent Command Center windows are supported; the native sidebar has Command
  Center, Evidence, Research, Comparison, and Chunks destinations.
- Layout model: native sidebar/detail `NavigationSplitView` with live Command Center, Evidence,
  Research, Comparison, and Chunks destinations.
- State ownership: scene-owned `CommandCenterStore`, `DocumentImportStore`, `ResearchCanvasStore`,
  `ComparisonTimelineStore`, and `ChunkInspectorStore` use explicit loading/failure states and do
  not fabricate evidence.
- Persistence: immutable content-addressed artifacts, hash-locked PostgreSQL migrations, pgvector,
  append-only acquisition/decision/duplicate/outbox evidence, and metadata-only trace JSONL persist
  below an exact owner-private data root.
- Services: typed Swift clients use authenticated Unix-domain IPC by default; loopback TCP is an
  opt-in development path only. They consume local runtime, evidence, research, comparison, and
  chunk contracts; Python shares runtime probes with `atlas doctor` and exposes owner-private CLI
  boundaries.
- App Intents / Foundation Models / advanced capabilities: not enabled.
- Folder/module structure: Swift contract/client/store code is separated from SwiftUI; Python contracts are separated from deterministic services and transport adapters.

## Build And Run

- Project type: Python uv workspace plus a SwiftPM macOS GUI executable.
- Build command: `swift build --package-path apps/macos --product RSIAtlas`.
- Run command: `./script/build_and_run.sh`.
- `script/build_and_run.sh` status: implemented with an explicitly labeled per-user `launchctl`
  engine job, local readiness checks, `.app` staging, foreground launch, canonical
  debug/log/telemetry/verify modes, and authenticated release-IPC mode. Release-IPC operation is
  development evidence, not a signed package or clean-install proof.
- Codex Run action status: `.codex/environments/environment.toml` points to the project-local script.

## Design System

- Apple Design Resources checked: not required for this native foundation shell; current visual-kit claims remain unverified.
- Platform UI kit/version: system SwiftUI controls on macOS 15+.
- SF Symbols/Icon Composer status: system SF Symbols are used; custom icon work is not started.
- Native structures: `WindowGroup`, `NavigationSplitView`, sidebar list, toolbar, keyboard shortcut, progress, list sections, and `ContentUnavailableView`.
- Adaptive states: runtime loading/healthy/failure and Evidence empty/uploading/awaiting-review/
  rejected/duplicate/failure states are implemented. Password presentation is contract-tested for a
  future authoritative profiler; encrypted markers remain unknown and quarantined. Development
  research, retrieval, report, and long-data surfaces do not close their production acceptance gates.
- Visual style: restrained native graphite/system surfaces with semantic status accents; no custom chrome or decorative animation.
- Motion rules: no decorative motion; system progress behavior only.
- Accessibility requirements: semantic labels and identifiers, separate remediation rows, keyboard
  refresh, VoiceOver-order accessibility-tree proof, system text/colors, compact-window scrolling,
  Light/Dark, increased contrast, large text, Reduce Motion, and multi-window behavior are verified
  in the development app. Debug-only QA overrides do not change release behavior.

## Test Strategy

- Unit tests: exact-head full-regression evidence is recorded in the iteration log below. Its test
  counts are development evidence only and do not replace release-artifact, signing, notarization,
  or clean-install verification.
- Integration tests or mocks: real PostgreSQL 17.10/pgvector 0.8.5 integration runs alongside
  FastAPI `TestClient`; Swift injects a real data-loading boundary and decodes the shared fixture.
- UI/manual smoke: historical development observations include degraded-only-model baseline;
  PostgreSQL/engine fault recovery; clean, malformed, rejected-signature, encrypted-marker, and
  exact-duplicate imports; same-request retry; truthful raw hash and quarantine copy; keyboard and
  VoiceOver order; 1120×760 and 860×600 content layouts; Light/Dark, increased contrast, large
  text, Reduce Motion, and a second window. Current foreground runtime proof is partial, not a
  production-release claim.
- Release smoke: not in scope; the staged app is an unsigned local debug artifact.
- Commands: `uv lock --check`, `uv run ruff check packages services infra script tests`,
  `uv run ruff format --check packages services infra script tests`, `uv run mypy packages services infra`,
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
- Signing team: Developer ID team `2NY8A789TN`; the usable local identity is installed, but the
  exact candidate remains unsigned.
- Sandbox/entitlements: the repository matrix is reviewed for authenticated UDS and no release TCP
  API; signed-artifact hardened-runtime and entitlement validation remain open.
- Privacy manifest: not created because this slice is not a release candidate.
- Privacy disclosures: not prepared.
- Assets: no custom app icon, screenshots, or marketing assets.
- Metadata: not prepared.
- Review notes: not applicable; the approved design selects Developer ID distribution outside the Mac App Store.
- Repository-local packaging is closed for embedded CPython, PostgreSQL, pgvector, the engine,
  explicit operational resources, native dependency relocation, lifecycle supervision, and the
  pre-sign artifact/license inventory. Remaining release blockers are the private notary API key,
  exact nested Developer ID signing, Apple acceptance/stapling, Gatekeeper and clean-user launch,
  signed-release zero-egress, upgrade/rollback, and Keychain-wrapped backup keys.

## Iteration Log

| Date | Gate | Change | Verification | Next blocker |
| --- | --- | --- | --- | --- |
| 2026-07-21 | Runtime final-review remediation | Added explicit Python no-bytecode launch, artifact-inventory signing preflight, authenticated-token wait, and lock/identity-based PostgreSQL orphan recovery. | At code commit `d303660`: **1313 passed, 1 skipped** Python; **55 Swift tests**; Swift build; lock/Ruff/format/mypy/parser governance. Independent re-review approved; immutable normal app launch and actual engine-crash/restart smokes passed. | Private notary API credentials; exact nested sign/notarize/staple/Gatekeeper/clean-user proof; hosted Actions billing. |
| 2026-07-21 | Embedded direct-download runtime closure | Added isolated CPython/PostgreSQL/pgvector, recursively relocated native providers, explicit runtime resources, app-managed engine/database lifecycle, artifact-derived inventory/license evidence, and fail-closed final provenance. Fixed collector startup errors being mislabeled as client input. | At code commit `641f12912700`: **1308 passed, 1 skipped** Python; **55 Swift tests**; Swift build; lock/Ruff/format/mypy/parser governance. Live unsigned app readiness and clean quit passed. | Private notary API credentials; exact nested sign/notarize/staple/Gatekeeper/clean-user proof; hosted Actions billing; model/provider and owner-sealed acceptance gates. |
| 2026-07-18 | Foundation contract | Added strict Python and Swift status contracts, deterministic diagnostics, CLI, and loopback API. | Final gate: 11 Python tests, 8 Swift tests, Ruff, strict mypy, uv lock check, and Swift product build passed. | Add persistence and artifact-store diagnostics in a separate slice. |
| 2026-07-18 | Native shell | Added a native sidebar/detail Command Center with loading, healthy, failure, retry, and keyboard refresh behavior. | Foreground accessibility and visual inspection proved healthy state, engine-down state via `⌘R`, and same-window recovery through Retry. | Minimum-window drag could not be established through the current UI-control surface; compact layout remains unverified. |
| 2026-07-18 | Runtime lifecycle | Replaced shell-owned background execution with an explicitly labeled per-user `launchctl` job and condition-based shutdown. | A separate shell confirmed the engine remained `running` and returned the healthy 3-component contract after `build_and_run.sh --verify` exited. | Replace development loopback transport with authenticated release IPC in a separate security milestone. |
| 2026-07-18 | Independent review | Hardened exact app-process ownership, pre-side-effect mode validation, latest-request-wins refresh, and non-empty diagnostics. | Reviewer re-check found all four findings resolved with no new Critical or Important regression. | Complete real-probe Task 6 and its foreground/fault acceptance matrix. |
| 2026-07-18 | Phase 1 durable runtime | Connected the native Command Center to exact real probes for PostgreSQL/pgvector, immutable artifacts, offline policy, local traces, resources, models, and contract/API truth. | 660 Python and 21 Swift tests; Ruff/format/mypy/lock/build gates; disposable PostgreSQL/artifact/engine fault recovery; persistence; process/socket proof; development `atlas doctor` zero-egress; foreground compact, appearance, accessibility, and multi-window passes. Independent source review approved `2669500` and the QA delta through `f8f9bcb` with no Critical/Important findings. | Phase 2 document-intelligence admission/import plan; release IPC, signing, backup/restore, and exact release-artifact zero egress remain later gates. |
| 2026-07-19 | Phase 2A secure admission | Added strict native/Python admission contracts, bounded file-backed upload, raw-first immutable publication, conservative decisions, append-only acquisition history, exact-duplicate isolation, and the native Evidence destination. | 827 Python and 43 Swift tests; hard engine kill and orphan recovery; PostgreSQL-down raw retention and same-ID retry; byte/record persistence across full restart; live API/direct-CLI coexistence; adversarial boundary matrix; foreground import/accessibility/appearance/multi-window proof; independent reviews found no remaining Critical/Important findings through `a4f75c9`. | Phase 2B promoted parser/preflight/canonical-page evidence; release IPC/signing/backup remain later gates. |
| 2026-07-19 | Phase 2B Tier-0 canonical evidence | Added governed PDF parser dependency approval, Seatbelt document worker, preflight/parse attempt journals, development-qualified `pypdf` parse, CAS-first canonical pages, processing API, and Evidence inspector page view. Docling remains blocked; no production promotion. | 935 Python and 44 Swift tests; ruff/mypy/lock; Seatbelt worker + dependency governance; canonical persistence/idempotency/corruption; processing API contract tests; Swift decode + debug/release builds; `build_and_run.sh --verify`. | Phase 2C chunking; Docling/OCR; sealed holdout production promotion; release IPC/signing/backup. |
| 2026-07-19 | Phase 2B re-review remediation | Cleared Important review blockers through `c4263e0`: preflight-before-parse, Process PDF admission/assessment gate, Keychain Seatbelt Mach canary, honest Task 8/9 evidence language. Independent re-review: approve-with-nits. | Focused remediation: Seatbelt Keychain canary, processing-pipeline/preflight/API tests, Swift EvidencePresentationTests. | Phase 2C five chunkers + inspect APIs; Docling remains blocked. |
| 2026-07-19 | Phase 2C five chunkers (dev) | Added chunk contracts + full §13.2 registry, five implemented families, frozen intrinsic goldens, migration `0007`, CAS-first chunk-set persistence, and loopback chunk inspect APIs. No embeddings/indexes/publication. Docling untouched. | **973** Python and **44** Swift tests; ruff/mypy/lock; chunk contract/unit/benchmark/persistence/API tests. | Phase 2D dense/lexical indexes + atomic publication; criterion 15 production-ready parent-child/table; sealed holdout; native chunk inspector UI optional. |
| 2026-07-19 | Phase 2D indexes + atomic publication (dev) | Added retrieval publication contracts (`INDEX_VALIDATED`/`PUBLISHED`), fixture-only deterministic embeddings (production embedding models blocked), migration `0008` staging dense pgvector + FTS lexical + exact-identifier rows, atomic activate/rollback active pointer, and loopback `indexing:start` / index-version list / `publication:activate` / `publication:rollback` APIs. Staging remains non-searchable until activation. Docling untouched. Mid-txn abort injection deferred. | Focused indexing/publication/API green; full suite **990** collected (known intermittent symlink-ancestor postgres harness EBADF under load); **44** Swift; ruff/mypy/lock. Tip through rollback API commit. | Phase 3 hybrid retrieval plan; production embedding promotion; criterion 15; OCR/parser promotion; interrupt/resume; Tantivy optional after benchmark. |
| 2026-07-19 | Phase 3 hybrid retrieval / research (dev) | Added retrieval/research/report contracts; active-only dense+lexical+exact hybrid search; intent-weighted RRF EvidencePacket with coverage/abstention + replay; Document Evidence specialist; assertion→citation→report draft gate; immutable review; migration `0009`; loopback research APIs. Fixture embeddings only; Docling/production embeddings/rerankers/LangGraph blocked. | **1009** Python and **44** Swift tests; ruff/mypy/lock; dependency-governance baseline refreshed for new workspace packages. | Production embedding + cross-encoder governance; LangGraph interrupt/resume; remaining specialists; calibrated judges; native Research Canvas/Report Studio; Phase 4 multi-chain planes; criteria 4–8/25–60 remain open. |
| 2026-07-19 | Phase 4 multi-chain / quantitative (dev) | Added observation/collector contracts; offline Bitcoin/EVM/Solana/market/governance/GitHub fixtures; raw envelopes before normalize; bitemporal observation persistence (`0010`); quarantine; reorg orphan stub; leakage-safe features; non-trading signals; fail-closed live + DuckDB/Parquet stubs; loopback `collectors:import-fixture` / observations list. No live RPC/WebSocket. | **1048** Python and **44** Swift tests; ruff/mypy/lock; dependency-governance baseline refreshed for collectors package. | Live providers; DuckDB/Parquet governance; full detector roster; criteria 43–44/61–81 remain open; Phase 5 monitoring. |
| 2026-07-19 | Phase 5 monitoring / comparison (dev) | Added monitoring/comparison contracts; deterministic detectors + rule matcher + materiality screen; alert dedup + append-only lifecycle; research invalidation; targeted research launch stub (no LangGraph); comparison matrix / cross-chain timeline with envelope links; fail-closed semantic triage; migration `0011`; loopback monitoring APIs. | **1077** Python collected / focused Phase 5 suite green; **44** Swift unchanged; ruff/mypy. | Calibrated semantic triage; LangGraph monitoring-driven research; native timeline/matrix UI; criteria 45/61/82–84 remain open; Phase 6 eval/release. |
| 2026-07-19 | Phase 6 engineering / release maturity (dev) | Added evaluation/Codex/recovery/release contracts; offline eval harness + frozen fixture + fail-closed judges; Codex sanitize/approval/patch gate with authority denial; filesystem backup/restore/Safe Mode/scrub; SBOM from `uv.lock`; fail-closed unsigned release checks; loopback Phase 6 APIs. | **1124** Python collected / focused Phase 6 suite **47** green; ruff/mypy. | Apple Developer ID signing, notarization, stapling, Gatekeeper clean-user, Keychain-wrapped backups, embedded signed Python, calibrated judges, live Codex App Server; criteria 85–134 remain open. |
| 2026-07-19 | OSS production-local promotion | Governed offline OSS embeddings (`oss_token_hash_v1` + fail-closed ONNX install), lexical rerank, linear workflow interrupt/resume (no LangGraph), optional monitored live HTTPS collectors, optional DuckDB/Parquet, system Tesseract OCR fail-closed, file-key AES-GCM backup, release entitlement matrix + SBOM write, native Research/Comparison/Chunks shells. Docling stays blocked; criteria remain Not proven; signing/notarization blocked on secrets. | Focused OSS tests green; Swift **44**; ruff/mypy on touched packages. | Install ONNX artifact for semantic embeddings; enable DuckDB optionally; provide Apple signing/notary secrets; Postgres-durable workflow; bind native timeline/research clients; sealed holdout PRODUCTION promotion. |
| 2026-07-19 | MiniLM ONNX embedder path | Stdlib BERT WordPiece + mean-pool `OfflineOnnxEmbedder`; install pins ONNX+vocab (fixed tip commit); optional `onnxruntime` extra governed; docs honesty. Still candidate, not sealed PRODUCTION. | Focused WordPiece/install tests green; optional e2e skip-if-artifact-missing. | Owner `--download` + `[onnx]` extra; sealed holdout PRODUCTION promotion. |
| 2026-07-19 | Must-have closure drive | Sealed promotion gates + fixtures; authenticated UDS release IPC (TCP behind flag); signing/notarization fail-closed scripts; multi-specialist extractive; heuristic triage + calibration; local model load/unload/OOM; reorg/WS honesty; injection suite; Codex qualify probe; Report Studio/matrix shells; OTel Swift→publication JSONL bridge. **No acceptance row marked Proven without owner secrets/corpus.** | Focused suites green; Swift **44**; release_check fail-closed. | Apple signing secrets; owner-sealed corpus; live Codex App Server; Swift UDS client; Docling. |
| 2026-07-19 | Native UDS client + development sealed packages | Swift `LocalEngineHTTP` defaults to authenticated AF_UNIX IPC (TCP only behind `RSI_ATLAS_ALLOW_LOOPBACK_TCP=1`); Command Center / Evidence / Research / Comparison / Chunks wired through it. Expanded `sealed_holdout_v1` v1.1; synthetic path emits distinct `development_sealed_package` (never PRODUCTION Proven); `run_sealed_promotion.py --development-package` offline E2E. | Focused sealed/IPC **203** + Swift **49** green. | Apple signing secrets; owner-sealed corpus for Section 33 Proven; live Codex App Server; Docling. |
| 2026-07-19 | E2E gate remediation (dev) | Refreshed PDF parser dependency-governance baseline hashes to current `pyproject.toml`/`uv.lock`; rewrote collector API test for auto-wired `CollectorServices`; ruff format + RUF012 ClassVar on ctypes `_fields_`; simplified Codex qualify probe for mypy. **Section 33 remains Not proven.** | Python **1180** passed / **1** skipped (occasional `test_start_runs_preflight_then_parse_for_quarantine` flake under full load); Swift **50**; ruff/mypy green. | Re-run full suite twice before claiming green; owner-sealed corpus for Section 33 Proven; Apple signing secrets; Docling. |
| 2026-07-20 | Exact-head development regression (`091caac`) | Reviewer ran `script/codex_full_regression.sh` end-to-end at exact commit `091caac`: the repository regression suite, Swift tests, Swift product build, lock, Ruff, strict mypy, and PDF parser dependency governance all completed. This is development evidence only. | **1225 passed, 1 skipped**; **50 Swift tests passed**; Swift `RSIAtlas` product built; lock/Ruff/mypy/parser governance passed. | Production, package, signing, notarization, and Gatekeeper clean-install proof remain open; no acceptance criterion moves to Proven. |
| 2026-07-20 | Truth-gate verification (`4507b854339a`) | Ran the exact-head static gates, two complete PostgreSQL-backed Python regressions, the complete Swift suite and product build, the development baseline smoke, and authenticated release IPC. The development baseline smoke was attempted but blocked by the resource policy because the host had less than the required 4 GiB free memory; swap and thermal limits were nominal. | Lock, Ruff check/format, strict mypy, parser governance, and diff checks passed; Python passed twice at **1227 passed, 1 skipped**; **51 Swift tests passed**; the `RSIAtlas` product built; `build_and_run.sh --release-ipc` reported `ipc_ready mode=unix_domain status=200`. The single optional ONNX artifact/runtime test remains skipped. | Re-run `build_and_run.sh --verify` after host memory pressure clears. This does not close model/provider qualification, package, signing, notarization, Gatekeeper clean-install, or owner-sealed acceptance gates. |
| 2026-07-20 | Final review remediation (`1aa80a693c3a`) | Closed the whole-branch review gap by enforcing durable Safe Mode inside default collector mutations, then fixed a real sandbox-worker pipe deadlock exposed by exact-head verification by draining bounded stdout/stderr while the worker runs. | `script/codex_full_regression.sh` passed at exact commit `1aa80a693c3a`: **1229 passed, 1 skipped**; **51 Swift tests passed**; the `RSIAtlas` product built; lock, Ruff check/format, strict mypy, parser governance, and diff checks passed. The single skip remains the optional ONNX artifact/runtime test. | The resource-blocked development baseline and all production/package/signing/notarization/Gatekeeper/owner-sealed gates remain open. |
| 2026-07-20 | Worker-supervision closeout (`697e0b8400bc`) | Added public-runner overflow and timeout regression tests covering limit-plus-one error classification, leader/child/process-group termination, and partial-output cleanup. The overflow test detects the pre-drain deadlock at `8e9cf0e`. Review first found that `33efc599b4a1` observed only the leader, then a resistant-child probe found that production escalation also stopped when the leader exited. The final test proves cleanup when a child ignores `SIGTERM`; the supervisor now escalates from process-group liveness and reaps the leader independently. | `script/codex_full_regression.sh` passed at code commit `697e0b8400bc`: **1232 passed, 1 skipped**; **51 Swift tests passed**; the `RSIAtlas` product built; lock, Ruff check/format, strict mypy, parser governance, and diff checks passed. Fresh runtime diagnostics still reported the resource policy blocked, so the foreground smoke was not run. | Reduce host pressure and rerun `build_and_run.sh --verify`; model/provider and all production/package/signing/notarization/Gatekeeper/owner-sealed gates remain open. |
