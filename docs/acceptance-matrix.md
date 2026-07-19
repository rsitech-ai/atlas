# RSI Atlas Acceptance Matrix

This is the live completion ledger for the normative criteria in Section 33 and the verification evidence in Appendix D of the approved specification. `Not proven` means current evidence is missing, partial, indirect, stale, or narrower than the criterion. A criterion moves to `Proven` only with a current source, automated check, and runtime or release artifact where the requirement demands one.

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
| 112–134 | Security, packaging, and recovery | Not proven | Authenticated Unix-domain release IPC + **native Swift UDS client** (TCP only behind `RSI_ATLAS_ALLOW_LOOPBACK_TCP=1`); SBOM; entitlement matrix with UDS policy; fail-closed signing/notarization scripts; file-key backup + recovery harness. No Developer ID/notarization/Gatekeeper/Keychain wrap Proven. | Apple secrets + nested sign/staple/Gatekeeper clean-user; Keychain wrap; embedded signed Python. |

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
| Release | Not proven | SBOM + entitlement matrix + fail-closed unsigned/notarization scripts. |
| Recovery | Not proven | Filesystem backup/restore/Safe Mode + file-key AES-GCM + recovery harness; Keychain wrap blocked. |

## Update rule

Every reviewed vertical slice updates the relevant row with exact commands, fixture names, commit, and runtime artifact. The final audit expands each grouped Section 33 range into individual criterion evidence and rejects any row supported only by source presence or a narrower smoke.

## Commands for newly added machinery (still Not proven for PRODUCTION claims)

```bash
uv run python script/run_sealed_promotion.py --component all
uv run python script/run_sealed_promotion.py --development-package --out dist/sealed_packages
uv run python script/run_engine.py --release-ipc   # UDS; do not combine with ALLOW_LOOPBACK_TCP
uv run python script/release_check.py --require-release
./script/package_release.sh
# ./script/sign_and_notarize.sh   # requires Apple secrets
uv run pytest packages/evaluation/tests/test_sealed_promotion.py packages/security/tests/test_ipc.py packages/monitoring/tests/test_triage.py packages/retrieval/tests/test_injection_suite.py -q
cd apps/macos && swift test --filter LocalEngine
```
