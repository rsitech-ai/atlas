# RSI Atlas Acceptance Matrix

This is the live completion ledger for the normative criteria in Section 33 and the verification evidence in Appendix D of the approved specification. `Not proven` means current evidence is missing, partial, indirect, stale, or narrower than the criterion. A criterion moves to `Proven` only with a current source, automated check, and runtime or release artifact where the requirement demands one.

## Section 33

| Criteria | Area | Current status | Current evidence | Closing evidence |
| --- | --- | --- | --- | --- |
| 1–9 | Product and UX | Not proven | Phase 1 Command Center plus Evidence; OSS slice adds Research / Comparison / Chunks native destination shells (honest empty states). Release-artifact accessibility incomplete. | Presets; complete workspaces/canvas/inspector/report/labs; release-artifact accessibility acceptance. |
| 10–24 | Ingestion | Not proven | Phase 2A–2D development evidence unchanged for admission/parse/chunk/index. System Tesseract OCR is fail-closed when absent; Docling remains blocked. No sealed scanned holdout or production parser promotion. | New-version handling; born-digital/scanned production parsing; measured fallback; production-promoted canonical provenance; production-ready parent-child/table; production embedding promotion; human interrupt/resume; citations; sealed holdout; retrieval benchmarks; full lineage/reprocessing; complete offline ingestion. |
| 25–40 | Retrieval | Not proven | Hybrid dense/lexical/exact, intent-weighted RRF, stdlib lexical post-RRF rerank, coverage/abstention. Offline `oss_token_hash_v1` candidate embedder + fail-closed ONNX artifact path governed; fixture default for tests. No sealed-holdout `PRODUCTION` promotion, neural cross-encoder, expansion, multi-hop, or injection suite. | All required planes, identity/as-of, intent, expansion, fusion/rerank, coverage/contradiction/repair/abstention, injection containment, degradation, replay, and promotion gates. |
| 41–60 | Research, agents, and reports | Not proven | Document Evidence specialist, plan validation, assertion/citation/report draft, immutable review; minimal linear interrupt/resume workflow (in-memory store; no LangGraph). Native Research destination shell only. Remaining specialists, Postgres-durable workflow, calibrated judges, Report Studio remain open. | Typed validated plans/specialists/tools, three ecosystems, comparison, monitoring trigger, assertions-first, exact multi-plane citations, numerical validation, calibrated judges, immutable review, edit validation, complete lineage. |
| 61–84 | Structured data and monitoring | Not proven | Fixture collectors + optional monitored live HTTPS with user allowlists (deny-by-default); optional DuckDB/Parquet when enabled; monitoring detectors/alerts/comparison payloads; native Comparison destination shell. WebSocket streams, calibrated semantic triage, full native timeline client remain open. | Shared raw envelope, scheduler controls, three chain families, market reconciliation/precision, governance/GitHub, bitemporal quality/replay, Parquet/DuckDB, leakage-safe features, non-trading signals, deterministic monitoring, alert/evidence navigation. |
| 85–102 | Models, evaluation, and observability | Not proven | Phase 1 metadata-only OTel + Phase 6 offline eval harness with fail-closed uncalibrated judges. OSS candidate embedders are not sealed-holdout production models. No calibrated judges, statistical CIs, or Swift-to-publication trace. | Interchangeable qualified providers, Apple fallback, isolated services, load/unload/arbiter/recovery, immutable artifacts, six dataset splits, evaluator ordering/calibration/statistics, regression mining, distributed local traces/privacy/retention and disabled exporters. |
| 103–111 | Codex | Not proven | Phase 6 product-plane sanitize/approval/gate/authority denial + loopback API. Not a qualified live Codex App Server suite. | Qualified local provider/app-server contracts, inspectable streams, isolated sanitized worktree, credential/private-data/network denial, approvals, no automatic authority, complete patch gate. |
| 112–134 | Security, packaging, and recovery | Not proven | Owner-private roots/sockets; SBOM; entitlement-matrix draft; fail-closed unsigned release checks; filesystem backup/Safe Mode; owner file-key AES-GCM backup (0600). No Developer ID signing, notarization, stapling, Gatekeeper clean-user, Keychain wrap, or embedded signed Python. | Signed/notarized exact artifact, capability/entitlement matrix, no TCP release API, exact release zero egress/allowlists, Keychain/worker containment, supply-chain/SBOM, embedded runtime, install/update/rollback/backup/restore/Safe Mode/rebuild/scrub/doctor/uninstall/incident proof. |

## Appendix D

| Capability | Current status | Required completion artifact |
| --- | --- | --- |
| Immutable evidence | Not proven | Phase 2A raw PDF publication + append-only admission evidence. Full scrub/supersession remain. |
| Durable workflow | Not proven | Parser-attempt journals + linear research workflow interrupt/resume (in-memory). Postgres-durable workflow checkpoints remain. |
| PDF intelligence | Not proven | Tier-0 `pypdf`; Docling blocked; system Tesseract OCR fail-closed when absent; sealed scanned holdout remains. |
| Chunking | Not proven | Five families with intrinsic goldens; parent-child/table production-ready policy remain. |
| Retrieval | Not proven | Hybrid RRF + lexical rerank; fixture + OSS token-hash candidate; ONNX fail-closed without artifact; no sealed PRODUCTION promotion. |
| Multi-agent research | Not proven | Document Evidence + linear interrupt/resume (in-memory); LangGraph deferred; native Research shell only. |
| Numerical integrity | Not proven | Calculation manifests, report revalidation, units/as-of tests. |
| Citation integrity | Not proven | Phase 3 direct_support citations with excerpt hashes; entailment judges remain. |
| Multi-chain | Not proven | Fixtures + optional monitored live HTTPS allowlist; WebSocket remain fail-closed. |
| Market data | Not proven | Fixture tick decimals + sequence-gap resnapshot; live streams remain. |
| Monitoring | Not proven | Deterministic monitoring + comparison payloads; native Comparison shell; calibrated triage blocked. |
| Local models | Not proven | Candidate OSS embedders + fail-closed ONNX; sealed qualification remain. |
| Evaluation | Not proven | Offline harness + fail-closed uncalibrated judges; calibration/statistics/promotion remain. |
| Observability | Not proven | Metadata-only local spans; Swift-to-publication trace remain. |
| Native application | Not proven | Command Center + Evidence + Research/Comparison/Chunks shells; release proof remain. |
| Zero egress | Not proven | Deny-by-default + optional collector allowlist; signed release-artifact proof remain. |
| Codex | Not proven | Product-plane sanitize/gate; live App Server qualification remain. |
| Security | Not proven | Signed peers, sandbox/entitlements, redaction, malicious containment. |
| Release | Not proven | SBOM + entitlement-matrix draft + fail-closed unsigned release check; notarization blocked on secrets. |
| Recovery | Not proven | Filesystem backup + optional file-key AES-GCM; Keychain wrap blocked. |

## Update rule

Every reviewed vertical slice updates the relevant row with exact commands, fixture names, commit, and runtime artifact. The final audit expands each grouped Section 33 range into individual criterion evidence and rejects any row supported only by source presence or a narrower smoke.
