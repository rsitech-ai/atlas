# RSI Atlas Full Product Delivery Roadmap

> This roadmap maps the approved specification to independently demonstrable phase plans. It is not a substitute for the detailed TDD implementation plan for each active phase.

## Completion contract

RSI Atlas is complete only when all 134 normative acceptance criteria in Section 33 and all 20 evidence rows in Appendix D have current authoritative proof against the built release artifact. Green unit tests, source presence, or a narrow smoke cannot close a broader criterion.

## Current evidence boundary

The reviewed Phase 1 chain through `647c25b`, Phase 2A chain through `113110c`, and Phase 2B
development chain through `6383861` (re-review approve-with-nits) prove the native-to-engine seam, immutable local artifacts,
Unix-socket PostgreSQL/pgvector persistence, exact runtime capability policy, isolated metadata-only
OpenTelemetry, strict model/resource boundaries, eight real bounded diagnostics, raw fail-closed PDF
admission with exact-duplicate and hard-kill recovery, and development-qualified Tier-0 parse plus
inspectable canonical pages under Seatbelt (Docling blocked; not production-promoted). Current checks
include 935 PostgreSQL-configured Python tests, 44 Swift tests, foreground fault/recovery and
accessibility/appearance/multi-window proof, restart persistence, exact process/socket evidence, and
development admission/worker zero egress. This does not complete document intelligence or a full
release criterion: no production-promoted parser, OCR/scanned path, chunker, index, or workflow runs;
observability is not end-to-end Swift-to-publication; loopback HTTP remains development-only; and the
artifact is unsigned.

| Phase | Specification scope | Acceptance criteria | Current status | Phase demonstration |
| --- | --- | --- | --- | --- |
| 1. Foundation and local runtime | §§8–11, 25, 27, 29–32 foundation portions | 1–3, 17, 85–93, 99–102, 112–126, 127–134 foundations | Complete (development evidence) | Native Command Center controls and diagnoses a durable, enforced-offline, observable local runtime with immutable artifacts, PostgreSQL/pgvector, resource/model policy, recovery, and no hard-coded health. |
| 2. Document intelligence | §§12–15 | 10–24 plus Evidence Inspector portion of 6 | Phase 2A–2B complete (dev); 2C–2D missing | Native PDF import reaches immutable raw evidence, durable fail-closed admission, development-qualified Tier-0 parse, and inspectable canonical pages. Completion still requires production promotion/OCR, five chunkers, dense/lexical indexes, interrupt/resume, atomic publication, and complete offline proof. |
| 3. Retrieval and research | §§16–18 | 4–8, 25–60 | Missing | A frozen material question produces an inspectable plan, hybrid evidence packet, bounded specialist findings, deterministic calculations, exact citations, review, and an editable versioned report. |
| 4. Multi-chain and quantitative data | §§19–23 | 43–44 and 61–81 | Missing | Bitcoin, EVM, Solana, market, governance, and GitHub fixtures become bitemporal observations/features and support reproducible dossiers and comparison inputs. |
| 5. Monitoring and comparison | §24 and cross-surface UX | 45, 61, 82–84 plus comparison/timeline UX | Missing | A deterministic material change invalidates affected research, deduplicates an alert, launches targeted research, and appears on the cross-chain timeline/comparison matrix. |
| 6. Engineering and release maturity | §§25–32 complete | 85–134 | Missing | Frozen evaluations qualify components, Codex produces a gated patch from a sanitized bundle, and a signed/notarized release passes zero-egress, clean install/update/rollback, backup/restore, Safe Mode, and integrity recovery. |

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
