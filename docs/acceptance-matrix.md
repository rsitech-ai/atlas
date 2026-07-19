# RSI Atlas Acceptance Matrix

This is the live completion ledger for the normative criteria in Section 33 and the verification evidence in Appendix D of the approved specification. `Not proven` means current evidence is missing, partial, indirect, stale, or narrower than the criterion. A criterion moves to `Proven` only with a current source, automated check, and runtime or release artifact where the requirement demands one.

## Section 33

| Criteria | Area | Current status | Current evidence | Closing evidence |
| --- | --- | --- | --- | --- |
| 1–9 | Product and UX | Not proven | Phase 1 proves a real grouped Command Center, exact remediation/stale states, keyboard refresh, semantic identifiers and VoiceOver order, compact/typical sizing, Light/Dark, increased contrast, large text, Reduce Motion, and multi-window behavior in the unsigned development app. | Presets; complete workspaces/canvas/inspector/report/labs; release-artifact accessibility acceptance. |
| 10–24 | Ingestion | Not proven | Phase 2A through `113110c` directly proves the exact-duplicate half of criterion 10; strict schema validation at native/API/CLI/storage boundaries for criterion 17; hard engine-death recovery without duplicate durable publication for criterion 19; append-only acquisition/decision/outbox evidence and replay-conflict rejection for criterion 23; and development zero-egress/raw admission portions of criterion 24. Phase 2B through `6383861` adds development-only governed Tier-0 parse (qualified `pypdf`), Seatbelt worker isolation (including Keychain Mach denial), preflight-before-parse composition with Process PDF admission/assessment gating, append-only parser-attempt journals, CAS-first canonical JSON versions, and native/API canonical-page inspection—without production promotion, Docling/Tier-1, OCR/scanned fallback, chunkers, indexes, or publication. Independent 2B re-review: approve-with-nits (Important blockers cleared in `6383861`). No full criterion in 10–24 is closed. | New-version handling; born-digital/scanned production parsing; measured fallback; production-promoted canonical provenance; five chunkers; indexes and atomic publication; human interrupt/resume; citations; sealed holdout; benchmarks; full lineage/reprocessing; complete offline ingestion. |
| 25–40 | Retrieval | Not proven | No retrieval implementation. | All required planes, identity/as-of, intent, expansion, fusion/rerank, coverage/contradiction/repair/abstention, injection containment, degradation, replay, and promotion gates. |
| 41–60 | Research, agents, and reports | Not proven | No research/report implementation. | Typed validated plans/specialists/tools, three ecosystems, comparison, monitoring trigger, assertions-first, exact multi-plane citations, numerical validation, calibrated judges, immutable review, edit validation, complete lineage. |
| 61–84 | Structured data and monitoring | Not proven | No collector/observation/feature/monitoring implementation. | Shared raw envelope, scheduler controls, three chain families, market reconciliation/precision, governance/GitHub, bitemporal quality/replay, Parquet/DuckDB, leakage-safe features, non-trading signals, deterministic monitoring, alert/evidence navigation. |
| 85–102 | Models, evaluation, and observability | Not proven | Phase 1 through `647c25b` has isolated metadata-only OpenTelemetry, exact safe span/context registries, owner-private cross-process JSONL, raw-SDK defense, strict immutable model metadata and production-promotion refusal, an unavailable no-I/O provider, deterministic resource leases, real native diagnostics, fault recovery, and current development-component zero-egress evidence. No real provider/model execution or qualification, evaluation plane, distributed Swift-to-publication trace, retention system, or release-artifact proof exists yet. | Interchangeable qualified providers, Apple fallback, isolated services, load/unload/arbiter/recovery, immutable artifacts, six dataset splits, evaluator ordering/calibration/statistics, regression mining, distributed local traces/privacy/retention and disabled exporters. |
| 103–111 | Codex | Not proven | Codex is used to develop the repo; that is not product Codex-plane evidence. | Qualified local provider/app-server contracts, inspectable streams, isolated sanitized worktree, credential/private-data/network denial, approvals, no automatic authority, complete patch gate. |
| 112–134 | Security, packaging, and recovery | Not proven | Phase 1 has owner-private roots/sockets, Unix-only PostgreSQL, exact runtime capabilities, no root daemon or trading/wallet/signing code, bounded startup diagnostics, and recorded development `atlas doctor` zero-egress. PostgreSQL, artifact, and engine faults recover honestly. The staged app is unsigned development evidence only and still uses loopback HTTP. | Signed/notarized exact artifact, capability/entitlement matrix, no TCP release API, exact release zero egress/allowlists, Keychain/worker containment, supply-chain/SBOM, embedded runtime, install/update/rollback/backup/restore/Safe Mode/rebuild/scrub/doctor/uninstall/incident proof. |

## Appendix D

| Capability | Current status | Required completion artifact |
| --- | --- | --- |
| Immutable evidence | Not proven | Phase 2A adds raw selected-PDF publication, strict digest/size binding, append-only acquisition/decision/outbox evidence, exact duplicates, and restart persistence. Raw envelopes beyond PDF acquisition, supersession/new-version history, and full scrub remain. |
| Durable workflow | Not proven | Phase 2A proves hard engine termination during upload, safe orphan cleanup on restart, same-ID retry, and one durable acquisition/decision/outbox record. Phase 2B adds append-only parser-attempt started/terminal events and reconcile-abandoned recovery for preflight/parse. Publication resume and full workflow checkpoints do not exist. |
| PDF intelligence | Not proven | Phase 2B proves development-qualified Tier-0 born-digital parse (`pypdf`) and inspectable canonical pages with NFC/coordinate lineage; Docling stays blocked; OCR/scanned fallback, production promotion, and parser comparison gates remain. |
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
| Observability | Not proven | Phase 1 proves isolated metadata-only local spans, owner-private JSONL, privacy validation, and persistence; Swift-to-publication trace and retention remain. |
| Native application | Not proven | Phase 2A adds native PDF selection, bounded uploading, truthful quarantine/duplicate/rejection/failure presentation, same-request retry, stable accessibility IDs, compact/appearance/VoiceOver/keyboard/multi-window evidence. Phase 2B adds Evidence inspector controls for processing status and canonical page text/hashes. Parsed research surfaces and release proof remain. |
| Zero egress | Not proven | Development runtime and admission tests deny DNS, external TCP, mDNS, subprocess, parser, and model boundaries while allowing loopback plus the exact PostgreSQL socket. Phase 2B Seatbelt document-worker profile adds OS-enforced containment for parse/preflight children. Complete ingestion and exact signed release-artifact proof remain. |
| Codex | Not proven | Local provider, socket protocol, isolated worktree, sanitized fixture, approval, gated patch. |
| Security | Not proven | Signed peers, sandbox/entitlements, redaction, malicious containment. |
| Release | Not proven | SBOM, signed manifest, notarization, Gatekeeper, install/update/rollback. |
| Recovery | Not proven | Encrypted backup, fresh restore, index rebuild, raw replay, Safe Mode. |

## Update rule

Every reviewed vertical slice updates the relevant row with exact commands, fixture names, commit, and runtime artifact. The final audit expands each grouped Section 33 range into individual criterion evidence and rejects any row supported only by source presence or a narrower smoke.
