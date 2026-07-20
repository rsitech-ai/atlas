# RSI Atlas Full Product Delivery Roadmap

> This roadmap maps the approved specification to independently demonstrable phase plans. It is not a substitute for the detailed TDD implementation plan for each active phase.

## Completion contract

RSI Atlas is complete only when all 134 normative acceptance criteria in Section 33 and all 20 evidence rows in Appendix D have current authoritative proof against the built release artifact. Green unit tests, source presence, or a narrow smoke cannot close a broader criterion.

## Historical evidence boundary

> **Historical ledger (2026-07-19):** The phase ranges below preserve the evidence recorded when
> this roadmap was last updated. They are not an exact-head readiness assertion. Consult the live
> production plan and acceptance matrix for current development evidence and unresolved release gates.

The reviewed Phase 1 chain through `647c25b`, Phase 2A chain through `113110c`, Phase 2B
development chain through `6383861` (re-review approve-with-nits), Phase 2C development chain
through `a51545d`, Phase 2D development chain through `c634b25`, Phase 3 development slice
through `a64dfec`, Phase 4 development slice through `27d1656`, Phase 5 development slice
through `6d5d7a5`, and Phase 6 development slice through the tip prove the native-to-engine seam,
immutable local artifacts, Unix-socket PostgreSQL/pgvector persistence, exact runtime capability
policy, isolated metadata-only OpenTelemetry, strict model/resource boundaries, eight real
bounded diagnostics, raw fail-closed PDF admission with exact-duplicate and hard-kill recovery,
development-qualified Tier-0 parse plus inspectable canonical pages under Seatbelt (Docling
blocked; not production-promoted), five implemented chunking families with frozen intrinsic
benchmarks plus chunk-set persistence/inspect APIs, development dense/lexical staging indexes
with atomic publication activation under fixture embeddings, development hybrid retrieval
(dense+lexical+exact RRF, coverage/abstention), Document Evidence specialist,
assertion/citation/report draft gate, loopback research APIs, offline fixture collectors for
Bitcoin/EVM/Solana/market/governance/GitHub into bitemporal observations with quarantine,
leakage-safe features, non-trading signals, deterministic monitoring (change detection,
materiality, alert dedup/lifecycle, research invalidation, targeted research launch stub,
comparison/timeline payloads), offline evaluation harness with fail-closed judges, Codex
product-plane sanitize/gate/authority denial, development backup/restore/Safe Mode/scrub, and
SBOM plus fail-closed unsigned release checks. This does not complete document intelligence, live
multi-chain collection, calibrated semantic triage/judges, native comparison UI, signed/
notarized distribution, or a full release criterion: no production-promoted parser or embedding
model, OCR/scanned path, production reranker, LangGraph durability, remaining specialists,
calibrated judges, native Research Canvas/Report Studio/Evaluation/Codex labs, live
RPC/WebSocket providers, DuckDB/Parquet writers, continuous live monitors, Developer ID signing,
notarization, or embedded signed Python; observability is not end-to-end Swift-to-publication;
loopback HTTP remains development-only; and the artifact is unsigned.

| Phase | Specification scope | Acceptance criteria | Current status | Phase demonstration |
| --- | --- | --- | --- | --- |
| 1. Foundation and local runtime | §§8–11, 25, 27, 29–32 foundation portions | 1–3, 17, 85–93, 99–102, 112–126, 127–134 foundations | Complete (development evidence) | Native Command Center controls and diagnoses a durable, enforced-offline, observable local runtime with immutable artifacts, PostgreSQL/pgvector, resource/model policy, recovery, and no hard-coded health. |
| 2. Document intelligence | §§12–15 | 10–24 plus Evidence Inspector portion of 6 | Phase 2A–2D complete (dev); production promotion/OCR/interrupt still open | Native PDF import reaches immutable raw evidence, durable fail-closed admission, development-qualified Tier-0 parse, inspectable canonical pages, five development chunkers, fixture dense/lexical indexes, and atomic publication activation. Completion still requires production promotion/OCR, interrupt/resume, and complete offline proof. |
| 3. Retrieval and research | §§16–18 | 4–8, 25–60 | Phase 3 development slice closed (hybrid retrieve / document specialist / cited draft); full criteria open | Development loopback APIs produce an inspectable plan, hybrid evidence packet (or abstention), Document Evidence finding, cited report draft, and immutable review. Production rerankers, LangGraph, remaining specialists, native Report Studio, and criteria 4–8/25–60 remain open. |
| 4. Multi-chain and quantitative data | §§19–23 | 43–44 and 61–81 | Phase 4 development slice closed (offline fixtures / bitemporal observations); full criteria open | Offline Bitcoin/EVM/Solana/market/governance/GitHub fixtures share raw-envelope → observation contracts with quarantine, pinned identity, leakage-safe features, and non-trading signals. Live providers, DuckDB/Parquet, and criteria 43–44/61–81 remain open. |
| 5. Monitoring and comparison | §24 and cross-surface UX | 45, 61, 82–84 plus comparison/timeline UX | Phase 5 development slice closed (deterministic monitoring / comparison payloads); full criteria open | Deterministic material change yields deduplicated alert, research invalidation, targeted research launch stub, and comparison/timeline payloads with envelope links. Semantic triage blocked; native UI and criteria 45/61/82–84 remain open. |
| 6. Engineering and release maturity | §§25–32 complete | 85–134 | Phase 6 development slice closed (offline eval / Codex gate / backup+Safe Mode / unsigned release honesty); full criteria open | Offline frozen eval harness, fail-closed judges, Codex sanitize+gate with no automatic authority, development backup/restore/Safe Mode/scrub, SBOM + fail-closed unsigned release checks. Signing/notarization, calibrated judges, live Codex App Server, and criteria 85–134 remain open. |

## Governed decisions

The parser/fallback order, OCR, VLM, embedding model, reranker, reasoning and judge models, MLX versus compatible runtime, chunk sizes, semantic thresholds, fusion weights/counts, optional Tantivy backend, first non-Ethereum EVM network, market providers, protocol adapters, reference subjects, and encrypted-artifact policy cannot be selected by convenience. Each requires a frozen benchmark, licensing/supply-chain review, resource evidence, versioned production policy, and rollback.

## Delivery rules

1. Each active phase has a detailed plan under `docs/superpowers/plans/` with exact files, test-first steps, verification commands, fixtures, security checks, migrations, and rollback.
2. UI consumes reviewed contracts; it does not define research truth or outrun stable engine behavior.
3. Every durable write preserves immutable inputs, versioned derivations, workspace/actor/trace context, and recovery semantics.
4. Every component that opens a file, socket, subprocess, model, or external source receives a zero-egress/capability test before promotion.
5. Every task is committed locally and receives task-scoped specification and quality review before the next writer task begins.
6. Every phase ends with a real foreground native-app demonstration and updates `docs/production-plan.md` with exact evidence and remaining blockers.
7. External release actions remain separate authority gates; repository-local work continues until the external gate is the first real blocker.
