# Phase 5 Monitoring and Comparison — Planning Stub

> **Status:** Planning only. Do not implement until Phase 4 development acceptance remains
> closed and this plan is expanded to full TDD task granularity.
> **Do not claim** Section 33 criteria 45, 61, or 82–84 closed from this stub.

**Goal:** From a published observation/feature change, run deterministic materiality detection,
deduplicate alerts, invalidate affected research, and surface the change on a cross-chain
timeline / comparison matrix—without live trading, unsigned release, or incomplete Phase 4 live
collectors.

**Depends on:** Phase 4 offline observation contracts + persistence (`0010`), Phase 3 research
run/report IDs for invalidation hooks.

**In scope (when expanded):**

1. Deterministic change detectors over observation/feature versions
2. Materiality screen + rule matcher (threshold / delta / finality / quality)
3. Alert deduplication identity + append-only alert events
4. Targeted research launch stubs (reuse Phase 3 plan validation; no LangGraph yet)
5. Research invalidation records when orphaned/quarantined inputs appear
6. Comparison matrix / timeline contracts (Swift UI later)

**Explicitly out of scope for first Phase 5 development slice:**

- Live collectors / WebSockets
- Native timeline UI completeness (criteria 4–8 remain open)
- Calibrated semantic triage LLMs
- Trading or exchange account access

**Next command when ready:** expand this stub into
`docs/superpowers/plans/YYYY-MM-DD-phase-5-monitoring-comparison.md` with exact files, RED tests,
and verification commands before writing code.
