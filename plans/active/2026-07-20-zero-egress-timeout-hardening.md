# Zero-egress timeout hardening

## Goal

- User-visible outcome: PR #2 has a trustworthy full-regression signal even when the workstation is heavily loaded.
- How to see it working: the verifier reports timeout when its observation budget is exhausted, cleanup assertions remain intact, and the security suite plus full regression pass.

## Current State

- Relevant paths: `infra/security/verify_zero_egress.py` and `packages/security/tests/test_zero_egress_verifier.py`.
- Existing behavior: the polling loop checks process completion after a potentially expensive refresh but before checking its deadline. Several integration tests also impose a 10-second outer watchdog around internal canary and cleanup budgets that can exceed that under severe scheduler load.
- Constraints: preserve fail-closed evidence, exact PID/start-identity cleanup, and the documented polling limitation. Do not terminate unrelated workstation processes.

## Target State

- Desired behavior: an observation that completes after the target deadline is classified as timed out; test watchdogs cover the verifier's internal maximum budget; unrelated-process sentinels outlive the test without depending on a five-second wall clock.
- Non-goals: replacing libproc polling with a new kernel event facility, changing sandbox policy, or claiming release-artifact zero-egress proof.

## Risks and Failure Modes

- A deadline-order change could misclassify a process whose exit was not observed before the deadline; fail-closed timeout classification is intentional.
- Relaxing fixture clocks could hide orphan cleanup regressions; marker assertions and exact cleanup tests must remain unchanged.
- Current machine load can still prevent a complete full-suite run from finishing promptly.

## Milestones

### M1. Prove deadline bug

- Goal: encode the fail-closed deadline requirement independently of scheduler timing.
- Files / systems: security verifier tests.
- Changes: add a unit test around a bounded wait helper.
- Verification: run the new test before implementation.
- Expected result: RED because the helper is absent.

### M2. Fix and harden fixtures

- Goal: implement deadline-first observation and remove undersized outer watchdogs.
- Files / systems: verifier and its tests.
- Changes: extract the wait loop, check elapsed budget before accepting completion, increase outer watchdog headroom, and use a long-lived sentinel.
- Verification: focused unit test, four cleanup tests, then the full security file.
- Expected result: PASS without weakening cleanup assertions.

### M3. Close PR evidence

- Goal: prove the entire branch and refresh PR #2.
- Files / systems: repository checks, PR body, independent reviewer.
- Changes: run full regression, commit and push the exact delta, update evidence, request re-review.
- Verification: exact commands recorded in the PR and this plan.
- Expected result: local regression green or an exact resource/external blocker retained as HOLD.

## Verification

- `uv run pytest packages/security/tests/test_zero_egress_verifier.py -q`
- `uv run pytest -q`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy packages --strict`
- Manual smoke: run a 0.2-second verifier target that sleeps for 10 seconds and confirm `timed_out=true` with no surviving child marker.

## Decision Log

- 2026-07-20: Treat budget exhaustion as timeout even if completion becomes observable after the deadline; this is the only fail-closed classification when the exact exit timestamp is unavailable.
- 2026-07-20: Preserve polling-based descendant semantics and its explicit evidence limitation; a kernel event redesign is outside this release-foundation PR.
- 2026-07-20: Establish the target deadline before releasing its gate; otherwise workstation suspension after release can consume unmetered target runtime.
- 2026-07-20: Give the gated supervisor handshake a fixed three-second setup budget independent of the target execution budget.

## Progress Log

- 2026-07-20: Reproduced three failures in the focused security file under load average above 160; identified deadline ordering and undersized fixture watchdogs.
- 2026-07-20: Added three deterministic RED regressions and implemented the minimal deadline-before-poll, deadline-before-release, and independent-handshake fixes.
- 2026-07-20: Security verifier file passed 31 tests. Exact full regression passed: lock, Ruff check/format, strict mypy, parser governance, 1,259 Python tests with one optional skip, 51 Swift tests, and the `RSIAtlas` product build.
- 2026-07-20: Next: commit and push the scoped fix, update PR #2 evidence, and request independent re-review.

## Rollback / Recovery

- If this fails: keep PR #2 unmerged and retain exact failure output.
- Safe fallback: revert only this focused security/test commit; the release assembly remains independently fail closed.
