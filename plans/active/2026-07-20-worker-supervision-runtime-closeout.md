# Worker Supervision And Runtime Closeout

## Goal

- User-visible outcome: document-worker overflow and timeout failures remain bounded, terminate the
  worker process group, remove partial outputs, and surface deterministic sanitized errors.
- How to see it working: focused tests exercise the public `DocumentWorkerRunner` subprocess path;
  the exact-head regression suite is green; runtime evidence truthfully records whether the host
  resource gate admits the foreground smoke.

## Current State

- Relevant paths:
  - `packages/ingestion/src/rsi_atlas_ingestion/worker_runner.py`
  - `packages/ingestion/tests/test_worker_runner.py`
  - `docs/acceptance-matrix.md`
  - `docs/production-plan.md`
- Existing behavior: commit `4cb6fc27c4d1` drains stdout/stderr concurrently with independent byte
  limits and routes timeout/overflow errors through process-group kill and partial-output cleanup.
- Constraints: Strict Offline remains the default; do not weaken timeout/output/resource limits; no
  production model, signing, packaging, push, or PR work.

## Target State

- Desired behavior:
  - Limit-plus-one output is rejected as `worker_output_too_large`, not misclassified as a timeout.
  - Timeout kills the process-group leader and removes worker-created partial output.
  - The rendered sandbox profile remains available for diagnostics after either failure.
  - The foreground runtime smoke runs only when `resource_policy` is not blocked.
- Non-goals: production API changes, dependency changes, model/provider admission, Apple release
  proof, or changes to safety thresholds.

## Risks and Failure Modes

- A fake worker that does not consume stdin can trigger `worker_stdin_failed` instead of the intended
  supervisor boundary.
- Output smaller than the platform pipe capacity would not distinguish the old wait-before-read
  deadlock from the current implementation.
- A timeout helper that exits before the deadline would fail to prove process-group termination.
- Host pressure may continue to block the foreground smoke; that is an observed external blocker,
  not authorization to reduce the resource threshold.

## Milestones

### M1. Add executable supervisor boundary tests

- Goal: exercise overflow and timeout through `DocumentWorkerRunner.run_echo_hash`.
- Files / systems: create
  `packages/ingestion/tests/test_worker_supervision_boundaries.py`.
- Changes:
  - Add a helper that writes mode-`0700` test-local shell executables.
  - Add a sandbox shim that consumes `-f <profile>` and execs the worker command.
  - Add an overflow worker that creates `partial.out` and emits exactly 64 KiB plus one byte while
    the runner ceiling is 64 KiB.
  - Make the overflow and timeout workers record leader and child PIDs outside the run directory;
    add a dedicated timeout worker whose child ignores `SIGTERM`, so escalation is tested
    independently of leader exit.
- Verification:
  - On current code, first create the tests without changing production code.
  - Apply the test file to a disposable worktree at `8e46baf` and run the overflow test.
  - Expected red result at `8e46baf`: `worker_timeout`, not expected
    `worker_output_too_large`.
  - Run all three tests on the current branch.
- Expected result: all public-runner boundary tests pass; only
  `document-worker.rendered.sb` remains after each failure; leader, child, and process group no
  longer exist, including when a child ignores `SIGTERM`.

### M2. Verify the affected worker and parser paths

- Goal: prove the tests did not weaken real Seatbelt, parser, containment, or static gates.
- Files / systems: document-worker, ingestion, security containment, repository static gates.
- Changes: production code changes are allowed only if M1 exposes a real defect and a new red test
  proves it first.
- Verification:
  - `uv run pytest packages/ingestion/tests/test_worker_supervision_boundaries.py packages/ingestion/tests/test_worker_runner.py packages/ingestion/tests/test_parser_service.py infra/security/tests/test_document_worker_sandbox.py -q`
  - `uv run ruff check packages services infra script tests`
  - `uv run ruff format --check packages services infra script tests`
  - `uv run mypy packages services infra`
  - `uv run python script/audit_pdf_parser_dependencies.py verify`
  - `git diff --check`
- Expected result: focused runtime/security tests and all static/governance gates pass.

### M3. Recheck runtime admission and exact-head regression

- Goal: capture current runtime truth and repository-wide evidence.
- Files / systems: local resource diagnostic, `script/build_and_run.sh`, full repository regression.
- Changes: update `docs/acceptance-matrix.md` and `docs/production-plan.md` with observed evidence.
- Verification:
  - `.venv/bin/atlas doctor --json`
  - If `resource_policy` is admitted: `./script/build_and_run.sh --verify`.
  - If blocked: do not run the smoke; record `blocked:external host resource pressure`.
  - `./script/codex_full_regression.sh`
- Expected result: exact-head full regression passes, while the foreground smoke is either observed
  green or explicitly blocked without a readiness overclaim.

### M4. Independent review and closeout

- Goal: independently assess test realism, cleanup semantics, and readiness wording.
- Files / systems: full branch diff from `91cc82d` to final code/evidence commit.
- Changes: fix any Critical/Important findings; record non-blocking gaps.
- Verification: reviewer approval plus a clean worktree and `git diff --check`.
- Expected result: no Critical/Important findings remain.

## Verification

- `uv run pytest packages/ingestion/tests/test_worker_supervision_boundaries.py packages/ingestion/tests/test_worker_runner.py packages/ingestion/tests/test_parser_service.py infra/security/tests/test_document_worker_sandbox.py -q`
- `uv run ruff check packages services infra script tests`
- `uv run ruff format --check packages services infra script tests`
- `uv run mypy packages services infra`
- `uv run python script/audit_pdf_parser_dependencies.py verify`
- `./script/codex_full_regression.sh`
- Manual smoke: `./script/build_and_run.sh --verify` only after resource admission.

## Decision Log

- 2026-07-20: Use deterministic public-runner tests rather than private-helper-only assertions so
  kill and cleanup behavior are included.
- 2026-07-20: Use an exact 64 KiB-plus-one fake-worker response to prove the configured stdout
  boundary and reproduce the pre-drain deadlock classification at `8e46baf`.
- 2026-07-20: Preserve the 4 GiB resource admission threshold; blocked host pressure is evidence,
  not a reason to weaken policy.

## Progress Log

- 2026-07-20: Design approved by the user's instruction to continue the previously recommended
  runtime/test closeout sequence.
- 2026-07-20: Current diagnostic still reports `resource_policy=blocked` and
  `model_registry=degraded`; all other components are healthy.
- 2026-07-20: M1 initially completed at `19a72ec`: two public-runner boundary tests passed and the
  overflow test failed against `8e46baf` with the expected old `worker_timeout` misclassification.
- 2026-07-20: Whole-branch review held M4 because the timeout assertion observed only the leader,
  so a leader-only termination mutation still passed, and because the overflow fixture did not use
  the exact limit-plus-one boundary.
- 2026-07-20: M1 evidence remediated at `0800bc9`: timeout and overflow now each spawn a child and
  prove leader, child, and process-group disappearance; overflow emits exactly 64 KiB plus one.
- 2026-07-20: Whole-branch re-review held M4 again after a resistant-child probe proved the
  supervisor escalated only while the leader was alive, allowing a child that ignored `SIGTERM` to
  survive. M1 is reopened for a red test and bounded production fix.
- 2026-07-20: M1 completed at `6329f5e`: the resistant-child test failed before the production fix
  because the process group remained alive, then passed after escalation was based on group
  liveness and leader reaping was made independent.
- 2026-07-20: M2 rerun: 17 worker/parser/containment tests passed; Ruff check/format, strict mypy,
  parser governance, and diff checks passed.
- 2026-07-20: M3 rerun at `6329f5e040f1`: full regression passed with 1232 Python tests,
  one optional ONNX skip, 51 Swift tests, and the product build. Fresh runtime admission remained
  blocked by host resources, so the foreground smoke was not run.
- 2026-07-20: Next: independent re-review of the remediated branch and reconciled evidence.

## Rollback / Recovery

- If tests are flaky: retain the existing production supervisor and remove only the new test commit
  after documenting the exact nondeterminism; do not weaken limits.
- If a production regression appears: revert only the new bounded fix commit after preserving its
  failing evidence; keep the previous `4cb6fc2` supervisor.
- Safe fallback: keep the branch local and leave the runtime status blocked until resource admission
  can be observed.
