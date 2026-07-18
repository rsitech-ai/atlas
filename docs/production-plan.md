# Production Plan: RSI Atlas

## Product Brief

- Target user: an individual quantitative crypto researcher first; a small crypto hedge-fund research team second.
- Primary job: turn local and explicitly collected crypto evidence into reproducible, inspectable research.
- Core workflow: acquire evidence, investigate a material question, inspect lineage, and publish a cited result. This foundation slice implements only local runtime readiness.
- Business model: a professional research workstation; commercialization is outside the foundation slice.
- Supported macOS versions: macOS 15 or newer on Apple Silicon; the reference hardware has 24–36 GB unified memory.
- Offline behavior: strict offline is the default. The current engine exposes a development endpoint only on `127.0.0.1` and enables no remote collector, model, telemetry exporter, update check, or remote resource.
- Data handled: this slice handles only runtime health metadata. It does not import research documents or persist analyst data.
- Privacy posture: zero egress for private data, prompts, embeddings, traces, reports, and evaluations.
- V1 scope: the approved design in `docs/superpowers/specs/2026-07-18-rsi-atlas-design.md`, delivered through independently verifiable vertical slices.
- Explicitly out of scope for this slice: PostgreSQL, artifact storage, ingestion, retrieval, models, collectors, LangGraph, report generation, XPC, signing, notarization, updates, backup, and recovery.

## Architecture

- Scene model: SwiftUI `WindowGroup` with a foreground native app lifecycle.
- Window roles: one workstation window in this slice; specialist and auxiliary windows are not implemented.
- Layout model: native sidebar/detail `NavigationSplitView` with one live Command Center destination.
- State ownership: scene-owned `CommandCenterStore`; loading and retry state is in memory.
- Persistence: none in this slice.
- Services: a typed Swift loopback client consumes `GET /v1/system/status`; Python shares deterministic diagnostics between that endpoint and `atlas doctor`.
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
- Adaptive states: loading, healthy, and recoverable engine-unavailable states are implemented. Empty research data, permission, import, and long-data states are outside this slice.
- Visual style: restrained native graphite/system surfaces with semantic status accents; no custom chrome or decorative animation.
- Motion rules: no decorative motion; system progress behavior only.
- Accessibility requirements: semantic labels, keyboard refresh, system text/colors, and native controls are implemented. VoiceOver, increased contrast, large text, and Reduce Motion runtime passes remain unverified.

## Test Strategy

- Unit tests: 11 Python tests and 8 Swift tests cover strict Pydantic models, deterministic status aggregation, cross-language fixtures, Swift strict decoding, schema compatibility, state transitions including out-of-order refresh, and HTTP response handling.
- Integration tests or mocks: FastAPI `TestClient` exercises the endpoint; Swift injects a real data-loading boundary and decodes the same response shape.
- UI/manual smoke: foreground launch, healthy Command Center, engine-down unavailable state, retry recovery, minimum and typical window sizes.
- Release smoke: not in scope; the staged app is an unsigned local debug artifact.
- Commands: `uv run pytest -q`, `uv run ruff check packages services`, `uv run mypy packages/contracts/src services/engine/src`, `swift test --package-path apps/macos`, `swift build --package-path apps/macos --product RSIAtlas`, and `./script/build_and_run.sh --verify`.

## Observability

- Logger subsystem: `ai.rsitech.RSIAtlas` is reserved; structured app logging is not implemented in this slice.
- Categories: runtime lifecycle and user refresh are the first planned categories.
- Key lifecycle/action events: engine startup/readiness and app process readiness are visible through the run script and `dist/engine.log`.
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
- Known blockers: embedded Python, local PostgreSQL, XPC/Unix-socket release transport, sandbox/hardened runtime, nested signing, notarization, SBOM, clean install, upgrade, rollback, backup, and restore.

## Iteration Log

| Date | Gate | Change | Verification | Next blocker |
| --- | --- | --- | --- | --- |
| 2026-07-18 | Foundation contract | Added strict Python and Swift status contracts, deterministic diagnostics, CLI, and loopback API. | Final gate: 11 Python tests, 8 Swift tests, Ruff, strict mypy, uv lock check, and Swift product build passed. | Add persistence and artifact-store diagnostics in a separate slice. |
| 2026-07-18 | Native shell | Added a native sidebar/detail Command Center with loading, healthy, failure, retry, and keyboard refresh behavior. | Foreground accessibility and visual inspection proved healthy state, engine-down state via `⌘R`, and same-window recovery through Retry. | Minimum-window drag could not be established through the current UI-control surface; compact layout remains unverified. |
| 2026-07-18 | Runtime lifecycle | Replaced shell-owned background execution with an explicitly labeled per-user `launchctl` job and condition-based shutdown. | A separate shell confirmed the engine remained `running` and returned the healthy 3-component contract after `build_and_run.sh --verify` exited. | Replace development loopback transport with authenticated release IPC in a separate security milestone. |
| 2026-07-18 | Independent review | Hardened exact app-process ownership, pre-side-effect mode validation, latest-request-wins refresh, and non-empty diagnostics. | Reviewer re-check found all four findings resolved with no new Critical or Important regression. | Keep compact-window, Light appearance, VoiceOver, signing, and release packaging explicitly unverified. |
