# RSI Atlas Acceptance Matrix

This is the live completion ledger for the normative criteria in Section 33 and the verification evidence in Appendix D of the approved specification. `Not proven` means current evidence is missing, partial, indirect, stale, or narrower than the criterion. A criterion moves to `Proven` only with a current source, automated check, and runtime or release artifact where the requirement demands one.

## Section 33

| Criteria | Area | Current status | Current evidence | Closing evidence |
| --- | --- | --- | --- | --- |
| 1–9 | Product and UX | Not proven | Foundation provides partial evidence for native launch, basic Command Center state, keyboard refresh, and semantic labels. | Full runtime control; presets; complete workspaces/canvas/inspector/report/labs; keyboard, VoiceOver, Reduce Motion, appearance, and multi-window acceptance. |
| 10–24 | Ingestion | Not proven | No ingestion implementation. | Duplicate/version, born-digital/scanned, evaluated fallback, canonical provenance, five chunkers, indexes, atomic publication/rollback, kill recovery, interrupt/resume, citations, benchmarks, lineage, offline run. |
| 25–40 | Retrieval | Not proven | No retrieval implementation. | All required planes, identity/as-of, intent, expansion, fusion/rerank, coverage/contradiction/repair/abstention, injection containment, degradation, replay, and promotion gates. |
| 41–60 | Research, agents, and reports | Not proven | No research/report implementation. | Typed validated plans/specialists/tools, three ecosystems, comparison, monitoring trigger, assertions-first, exact multi-plane citations, numerical validation, calibrated judges, immutable review, edit validation, complete lineage. |
| 61–84 | Structured data and monitoring | Not proven | No collector/observation/feature/monitoring implementation. | Shared raw envelope, scheduler controls, three chain families, market reconciliation/precision, governance/GitHub, bitemporal quality/replay, Parquet/DuckDB, leakage-safe features, non-trading signals, deterministic monitoring, alert/evidence navigation. |
| 85–102 | Models, evaluation, and observability | Not proven | No model/evaluation plane; engine log is not OpenTelemetry evidence. | Interchangeable qualified providers, Apple fallback, isolated services, load/unload/arbiter/recovery, immutable artifacts, six dataset splits, evaluator ordering/calibration/statistics, regression mining, distributed local traces/privacy/retention and disabled exporters. |
| 103–111 | Codex | Not proven | Codex is used to develop the repo; that is not product Codex-plane evidence. | Qualified local provider/app-server contracts, inspectable streams, isolated sanitized worktree, credential/private-data/network denial, approvals, no automatic authority, complete patch gate. |
| 112–134 | Security, packaging, and recovery | Not proven | Current slice has no root daemon and no trading/wallet/signing code; staged debug app is unsigned development evidence only. | Signed/notarized exact artifact, capability/entitlement matrix, no TCP release API, exact zero egress/allowlists, Keychain/worker containment, supply-chain/SBOM, embedded runtime/socket-only PG, install/update/rollback/backup/restore/Safe Mode/rebuild/scrub/doctor/uninstall/incident proof, durable non-trading boundary. |

## Appendix D

| Capability | Current status | Required completion artifact |
| --- | --- | --- |
| Immutable evidence | Not proven | Hash-verified artifacts/raw envelopes, supersession history, integrity scrub. |
| Durable workflow | Not proven | Deliberate termination and checkpoint recovery without duplicate publication. |
| PDF intelligence | Not proven | Born-digital/scanned fallback, exact region citation, parser comparison. |
| Chunking | Not proven | Five families, parent-child/table policy, labelled benchmark. |
| Retrieval | Not proven | Required plane traces, fusion/rerank scores, abstention. |
| Multi-agent research | Not proven | Typed plan, isolated specialists, strict tools, interrupt/resume, repair. |
| Numerical integrity | Not proven | Calculation manifests, report revalidation, units/as-of tests. |
| Citation integrity | Not proven | Coverage, exact locators, entailment, contradictions. |
| Multi-chain | Not proven | Reproducible EVM/Solana/Bitcoin snapshots and reorg/finality tests. |
| Market data | Not proven | Snapshot/delta sequence, fixed precision, gap recovery. |
| Monitoring | Not proven | Change/materiality/investigation/invalidation/deduplicated alert. |
| Local models | Not proven | Capability registry, hashes/licenses, resource/crash/fallback qualification. |
| Evaluation | Not proven | Versioned datasets, calibration, code/judge metrics, statistical comparison. |
| Observability | Not proven | Swift-to-publication trace, privacy mode, local retention. |
| Native application | Not proven | Presets, evidence overlay, report editing, graph/timeline, accessibility. |
| Zero egress | Not proven | Recorded network-denial test for the exact release artifact. |
| Codex | Not proven | Local provider, socket protocol, isolated worktree, sanitized fixture, approval, gated patch. |
| Security | Not proven | Signed peers, sandbox/entitlements, redaction, malicious containment. |
| Release | Not proven | SBOM, signed manifest, notarization, Gatekeeper, install/update/rollback. |
| Recovery | Not proven | Encrypted backup, fresh restore, index rebuild, raw replay, Safe Mode. |

## Update rule

Every reviewed vertical slice updates the relevant row with exact commands, fixture names, commit, and runtime artifact. The final audit expands each grouped Section 33 range into individual criterion evidence and rejects any row supported only by source presence or a narrower smoke.
