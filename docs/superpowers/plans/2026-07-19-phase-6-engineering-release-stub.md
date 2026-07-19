# Phase 6 Engineering and Release Maturity — Planning Stub

> **Status:** Planning only. Do not implement until Phase 5 development acceptance remains
> closed and this plan is expanded to full TDD task granularity.
> **Do not claim** Section 33 criteria 85–134 closed from this stub.

**Goal:** Qualify components via frozen evaluations, produce gated Codex patches from sanitized
bundles, and ship a signed/notarized release that passes zero-egress, clean install/update/
rollback, backup/restore, Safe Mode, and integrity recovery—without pretending loopback HTTP or
unsigned development builds are release evidence.

**Depends on:** Phase 5 monitoring development slice closed (deterministic alerts + comparison
contracts); Phases 1–4 development seams remain immutable.

**In scope (when expanded):**

1. Evaluation center contracts + frozen datasets / calibration hooks
2. Judge calibration gates (fail-closed until labelled sets exist)
3. Codex engineering integration (sanitized bundle → gated patch; no automatic authority)
4. Fault / adversarial suites beyond current development probes
5. Packaging, signing, notarization, update, backup/restore, Safe Mode, integrity recovery

**Explicitly out of scope for a first Phase 6 planning pass:**

- Closing criteria 85–134 without release-artifact proof
- Hosted telemetry / remote control planes
- Trading, wallet, or signing product surfaces

**Next command when ready:** expand this stub into
`docs/superpowers/plans/YYYY-MM-DD-phase-6-engineering-release.md` with exact files, RED tests,
and verification commands before writing code. Prefer slicing Phase 6 into independently
demonstrable plans (eval → Codex gate → packaging/release) rather than one monolithic land.
