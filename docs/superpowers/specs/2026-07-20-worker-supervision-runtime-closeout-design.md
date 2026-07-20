# Worker Supervision And Runtime Closeout Design

## Outcome

RSI Atlas should retain strict, bounded document-worker supervision under overflow and timeout
conditions, with executable regression evidence for process-group termination and partial-output
cleanup. The development runtime baseline should be retried only when the existing resource policy
admits work; the policy must not be weakened to manufacture a green smoke.

## Scope And Authority

- Add focused tests for stdout limit-plus-one rejection and integrated timeout cleanup.
- Re-run the current resource diagnostic and the real development smoke only when admitted.
- Update the existing evidence ledger with observed results.
- Keep production model admission, Apple signing, notarization, packaging, push, and PR creation out
  of scope.

## Considered Approaches

1. **Public-runner boundary tests with deterministic local helper executables — selected.** Exercise
   `DocumentWorkerRunner.run_echo_hash` through its real subprocess, pipe, timeout, kill, and cleanup
   path while replacing only `sandbox-exec` and the worker executable with test-local scripts. This
   verifies the complete supervisor contract without changing production code or relying on timing
   from a real PDF parse.
2. **Private `_drain_process_output` unit tests only.** Faster, but it would not prove that overflow
   and timeout errors reach process-group termination and partial-output cleanup.
3. **Real Seatbelt worker with oversized PDFs or arbitrary delays.** Closest to production, but the
   inputs would be slow, brittle, and unable to deterministically force a sleeping worker without a
   test-only production hook.

## Design

Create `packages/ingestion/tests/test_worker_supervision_boundaries.py`. A small test helper writes
owner-executable shell scripts below `tmp_path`: a sandbox shim that consumes the `-f <profile>`
arguments and execs the supplied worker, and bounded fake workers that first drain stdin and then
either emit an oversized response or sleep after recording their PID and a partial output.

The overflow test configures a one-byte stdout ceiling and requires
`DocumentWorkerRunnerError("worker_output_too_large")`; it verifies that worker-created output is
removed while the rendered sandbox profile remains for inspection. The timeout test configures a
short monotonic deadline, requires `DocumentWorkerRunnerError("worker_timeout")`, verifies the
process-group leader no longer exists, and verifies partial output cleanup.

These are supervisor boundary tests, not substitutes for the existing real Seatbelt echo, parser,
containment, and full-regression coverage. No production API or dependency changes are expected.

## Runtime And Evidence Rules

`atlas doctor --json` is the admission check. If `resource_policy` remains `blocked`, record the
development smoke as blocked and do not run or weaken `build_and_run.sh --verify`. Authenticated
release IPC evidence from the prior exact-head run remains valid but does not imply signing or
packaging readiness.

## Verification

- Prove the overflow regression test fails against pre-drain commit `8e46baf`.
- Run the new tests on the current branch.
- Run all document-worker and ingestion worker-runner tests.
- Run Ruff check/format, strict mypy, parser governance, and `git diff --check`.
- Run `script/codex_full_regression.sh` once after the test-only change.
- Obtain an independent read-only review of test realism and readiness wording.

## Non-Goals

- No change to byte ceilings, timeout durations, Safe Mode, model/provider status, or release gates.
- No synthetic claim that a resource-blocked foreground smoke passed.
- No external write, push, PR, signing, notarization, or package publication.
