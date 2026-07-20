# RSI Atlas Acceptance Matrix

This is the live completion ledger for the normative criteria in Section 33 and the verification evidence in Appendix D of the approved specification. `Not proven` means current evidence is missing, partial, indirect, stale, or narrower than the criterion. A criterion moves to `Proven` only with a current source, automated check, and runtime or release artifact where the requirement demands one.

## Exact-head development evidence

| Date | Evidence | Acceptance impact |
| --- | --- | --- |
| 2026-07-21 | At code commit `641f12912700`, `script/codex_full_regression.sh` passed: **1308 Python tests passed, 1 optional ONNX test skipped**; **55 Swift tests passed**; the Swift product built; lock, Ruff, format, strict mypy, and parser governance passed. The unsigned staged app separately proved live in-bundle Mach-O closure, embedded PostgreSQL/pgvector health, authenticated app-managed engine readiness, clean normal-quit shutdown, and an exact artifact/license inventory. | Repository gates are **repo-ready / unsigned runtime-proven**. Section 33 remains `Not proven`: Developer ID nested signing, Apple notarization/stapling, Gatekeeper clean-user launch, exact signed-release zero-egress, model/provider promotion, and other owner-sealed criteria remain open. |
| 2026-07-20 | At exact code commit `697e0b8400bc`, `script/codex_full_regression.sh` passed with **1232 passed, 1 skipped**; **51 Swift tests passed**; the Swift product built; lock, Ruff check/format, strict mypy, parser governance, and diff checks passed. Public-runner tests prove a limit-plus-one stdout response is classified as `worker_output_too_large`; timeout and overflow terminate the fake worker's leader, child, and process group and remove partial output. A resistant-child timeout test first failed because a child that ignored `SIGTERM` survived after leader exit; the production fix now escalates using group liveness and independently reaps the leader. Earlier review also caught that `33efc599b4a1` observed only the leader; `3241a75e48bc` closed that test-evidence gap before the resistant-child production defect was found. The overflow test still fails against pre-drain commit `8e9cf0e` with the historical `worker_timeout` misclassification. A fresh `atlas doctor --json` reports `resource_policy=blocked`, so the foreground development smoke was not run. | Worker-supervision implementation and regression evidence are stronger and repository gates remain green. Host resource admission is still **blocked:external**; no foreground runtime pass, production model, package, signing, notarization, or clean-install claim is added. Every Section 33 and Appendix D status remains **Not proven**. |
| 2026-07-20 | At exact commit `1aa80a693c3a`, `script/codex_full_regression.sh` passed after whole-branch review remediation: **1229 passed, 1 skipped**; **51 Swift tests passed**; the Swift product built; lock, Ruff check/format, strict mypy, parser governance, and diff checks passed. The remediation added a service-level durable Safe Mode recheck for collector mutations and bounded concurrent draining for sandbox-worker output. The one skip remains the optional ONNX artifact/runtime test. | Exact-head repository evidence is green. This does not turn the earlier resource-blocked development baseline into a pass, and it does not prove production models, packaging, signing, notarization, or clean install. Every Section 33 and Appendix D status remains **Not proven**. |
| 2026-07-20 | At exact commit `4507b854339a`, lock, Ruff check/format, strict mypy, parser governance, and diff checks passed; two complete PostgreSQL-backed runs each passed at **1227 passed, 1 skipped**; **51 Swift tests passed**; the Swift product built; authenticated release IPC returned `ipc_ready mode=unix_domain status=200`. `build_and_run.sh --verify` was also attempted and correctly stopped at the resource-policy gate because current free host memory was below 4 GiB; swap and thermal limits were nominal. The one skip is the optional ONNX artifact/runtime test. | Stronger repository and authenticated development-runtime evidence only. The resource-blocked development baseline is not recorded as a pass, and release IPC is not signed-package evidence. Every Section 33 and Appendix D status remains **Not proven**. |
| 2026-07-20 | A reviewer ran `script/codex_full_regression.sh` end-to-end at exact commit `091caac`: **1225 passed, 1 skipped**; **50 Swift tests passed**; the Swift `RSIAtlas` product built; lock, Ruff, strict mypy, and PDF parser dependency governance passed. | Development-complete / partially runtime-proven only. Every Section 33 and Appendix D status remains **Not proven**; production, package, signing, notarization, and clean-install evidence remain open. |

## Section 33

| Criteria | Area | Current status | Current evidence | Closing evidence |
| --- | --- | --- | --- | --- |
| 1–9 | Product and UX | Not proven | Command Center + Evidence; Research Canvas with Report Studio panel; Comparison timeline + matrix shell; Chunk Inspector bound to loopback. Release-artifact accessibility incomplete. | Presets; polished Report Studio; labs; release accessibility acceptance. |
| 10–24 | Ingestion | Not proven | Phase 2A–2D unchanged. Tesseract OCR fail-closed when absent; Docling blocked. Sealed-holdout **promotion machinery** + expanded synthetic fixture (`sealed_holdout_v1` v1.1) can emit **development_sealed_package** evidence offline — still **not** owner-sealed PRODUCTION Proven. | Owner-sealed holdout corpus; born-digital/scanned production parsing; Docling if offline+license. |
| 25–40 | Retrieval | Not proven | Hybrid RRF + lexical rerank; OSS token-hash + MiniLM ONNX candidate; sealed promotion gates fail-closed without owner evidence; development sealed packages are labeled distinctly from PRODUCTION; injection suite self-check. No neural cross-encoder PRODUCTION. | Sealed holdout PRODUCTION; neural rerank if governable; full injection containment under live retrieve. |
| 41–60 | Research, agents, and reports | Not proven | Multi-specialist extractive orchestration (document/tokenomics/market/on_chain/governance/treasury/security/contradiction); Postgres-durable linear interrupt/resume; Report Studio minimal native panel. LangGraph deferred (ponytail). Calibrated judges remain open. | LangGraph or equivalent if license OK; calibrated judges; full Report Studio. |
| 61–84 | Structured data and monitoring | Not proven | Live HTTPS allowlist collectors; reorg `apply_reorg`; WebSocket fail-closed; DuckDB optional; heuristic triage with frozen calibration fixture (`run_heuristic_triage`); comparison matrix shell. | Live WebSocket under egress policy; human-labelled triage calibration Proven; full matrix cells UI. |
| 85–102 | Models, evaluation, and observability | Not proven | Sealed promotion machinery; local model load/unload/OOM recovery; Apple Foundation Models honest unavailable; offline eval harness; Swift→publication local JSONL bridge (`record_swift_to_publication_trace`) — not full native Swift join. | Owner-sealed PRODUCTION models; calibrated judges/CIs; Swift process OTel join. |
| 103–111 | Codex | Not proven | Product-plane sanitize/gate + `qualify_codex_app_server` fail-closed without binary / deny-network. Live App Server suite not executed. | Live Codex App Server under isolated worktree + deny-network proof. |
| 112–134 | Security, packaging, and recovery | Not proven | Self-contained unsigned ARM64 app with supervised engine/PostgreSQL/pgvector, authenticated UDS IPC, live native dependency closure, exact artifact/license inventory, fail-closed sign/notarize workflow, and file-key backup/recovery harness. No Developer ID/notarization/Gatekeeper/Keychain wrap Proven. | Private notary credentials; exact nested sign/notarize/staple/Gatekeeper/clean-user proof; signed-release zero-egress; Keychain wrap. |

## Appendix D

| Capability | Current status | Required completion artifact |
| --- | --- | --- |
| Immutable evidence | Not proven | Phase 2A raw PDF publication + append-only admission evidence. Full scrub/supersession remain. |
| Durable workflow | Not proven | Linear research workflow interrupt/resume with Postgres attempts (`0012`); multi-specialist extractive; LangGraph deferred. |
| PDF intelligence | Not proven | Tier-0 `pypdf`; Docling blocked; Tesseract fail-closed; sealed scanned holdout remains. |
| Chunking | Not proven | Five families with intrinsic goldens; sealed chunk-policy promotion machinery only. |
| Retrieval | Not proven | Hybrid RRF + lexical rerank; injection suite; sealed PRODUCTION still owner-corpus gated. |
| Multi-agent research | Not proven | Multi-specialist extractive (no LangGraph); Report Studio minimal panel. |
| Numerical integrity | Not proven | Calculation manifests, report revalidation, units/as-of tests. |
| Citation integrity | Not proven | Phase 3 direct_support citations; entailment judges remain. |
| Multi-chain | Not proven | Fixtures + live HTTPS allowlist; reorg apply; WebSocket fail-closed. |
| Market data | Not proven | Fixture ticks + sequence-gap; live streams remain. |
| Monitoring | Not proven | Deterministic detectors + calibrated heuristic triage (synthetic calibration); matrix shell. |
| Local models | Not proven | Candidate OSS embedders + load/unload/OOM; AFM unavailable honesty; sealed PRODUCTION remain. |
| Evaluation | Not proven | Offline harness + sealed promotion gates; synthetic path emits `development_sealed_package` only. |
| Observability | Not proven | Metadata-only local spans + Swift→publication JSONL bridge (not native Swift join). |
| Native application | Not proven | Command Center + Evidence + Research/Report Studio + Comparison + Chunks over authenticated local IPC (UDS default). |
| Zero egress | Not proven | Deny-by-default + optional collector allowlist; signed release proof remain. |
| Codex | Not proven | Product-plane + qualification probe; live App Server remain. |
| Security | Not proven | UDS release IPC + token auth + Swift UDS client; signed peers/notarization remain. |
| Release | Not proven | Unsigned runtime-proven app, live dependency closure, artifact-derived inventory, entitlement matrix, and fail-closed sign/notarize/provenance workflow. |
| Recovery | Not proven | Filesystem backup/restore/Safe Mode + file-key AES-GCM + recovery harness; Keychain wrap blocked. |

## Update rule

Every reviewed vertical slice updates the relevant row with exact commands, fixture names, commit, and runtime artifact. The final audit expands each grouped Section 33 range into individual criterion evidence and rejects any row supported only by source presence or a narrower smoke.

## Commands for newly added machinery (still Not proven for PRODUCTION claims)

```bash
uv run python script/run_sealed_promotion.py --component all
uv run python script/run_sealed_promotion.py --development-package --out dist/sealed_packages
uv run python script/run_engine.py --release-ipc   # UDS; do not combine with ALLOW_LOOPBACK_TCP
./script/build_and_run.sh --release-ipc            # engine UDS + native app with token auth
uv run python script/wait_engine_ipc.py --require-auth
uv run python script/release_check.py --require-release
./script/package_release.sh
# ./script/sign_and_notarize.sh   # requires Apple secrets
uv run pytest packages/evaluation/tests/test_sealed_promotion.py packages/security/tests/test_ipc.py packages/monitoring/tests/test_triage.py packages/retrieval/tests/test_injection_suite.py -q
cd apps/macos && swift test --filter LocalEngine
```
