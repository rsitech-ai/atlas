# Task 1: Durable Safe Mode State And Capability Guard

## Goal

Persist Safe Mode under `<data_root>/recovery/safe-mode.json` so a restart
retains the state, and fail closed whenever its on-disk state cannot be trusted.

## Authority Boundary

Only the assigned recovery implementation/tests and this report will change.
No external action or push is authorized.

## Current State

- `SafeModeController` is in-memory only.
- `SafeModeState` already enforces the full disabled-capability mask when active.

## Target State

- `SafeModeStore(data_root)` reads/writes the required state path safely.
- Unsafe state resolves to active Safe Mode with reason
  `safe_mode_state_unreadable`.
- `SafeModeController.require(capability)` raises `SafeModeBlocked` while that
  capability is disabled.

## Risks And Failure Modes

- A corrupt or attacker-controlled file must never silently clear Safe Mode.
- A write must not expose a partially written state or follow a symlink.
- Existing in-memory `SafeModeController()` callers must remain compatible.

## Milestones

### M1. Test desired persistence and capability guard behavior

- Files: recovery tests.
- Verification: focused test command is red because the persistence APIs are absent.

### M2. Add descriptor-safe storage and controller integration

- Files: `safe_mode.py`, package exports.
- Verification: focused recovery tests pass.

### M3. Review and commit the scoped slice

- Verification: focused test command, diff review, scoped commit.

## Verification

- `uv run pytest packages/recovery/tests/test_safe_mode_store.py -q`
- `uv run pytest packages/recovery/tests/test_safe_mode_store.py packages/recovery/tests/test_backup_restore.py -q`

## Decision Log

- 2026-07-20: Use a `SafeModeStore` rooted at `data_root`; its fixed state
  location is `data_root/recovery/safe-mode.json`.

## Progress Log

- 2026-07-20: M1 RED observed: all eight new tests failed because
  `SafeModeStore` did not exist.
- 2026-07-20: M2 completed: descriptor-safe store, restart-aware controller,
  fail-closed unsafe-state fallback, and capability guard implemented.
- 2026-07-20: M3 completed: scoped tests, package recovery suite, Ruff, and
  whitespace validation are green; committed as
  `feat(recovery): persist safe mode fail closed`.

## Rollback / Recovery

- Reverting the scoped commit restores the existing in-memory controller.
- Any unreadable state remains fail-closed rather than being deleted or repaired.

## Implementation

- Added `SafeModeStore(data_root)`, rooted at
  `data_root/recovery/safe-mode.json`, with `load`, `enter`, `exit`, and
  `save` operations.
- Reads open the state with `O_NOFOLLOW`, require a regular file owned by the
  current user with exact mode `0600`, bound the payload to 16 KiB, and validate
  it through `SafeModeState.model_validate_json`.
- Every read or validation failure resolves to active Safe Mode with the full
  capability mask and reason `safe_mode_state_unreadable`.
- Writes create a random same-directory temporary file through
  `O_CREAT | O_EXCL | O_NOFOLLOW`, set mode `0600`, write and `fsync` it,
  atomically `os.replace` it by directory descriptor, then `fsync` the parent.
- `SafeModeController` accepts an optional store while preserving the existing
  no-argument in-memory behavior. Its new `require` method raises
  `SafeModeBlocked` for disabled capabilities.

## TDD Evidence

### RED — before production implementation

```text
$ uv run pytest packages/recovery/tests/test_safe_mode_store.py -q
FFFFFFFF                                                                 [100%]
...
E       AttributeError: module 'rsi_atlas_recovery.safe_mode' has no attribute 'SafeModeStore'. Did you mean: 'SafeModeState'?
...
8 failed in 0.19s
```

The failures were the expected missing-persistence API signal; no production
implementation existed before this run.

### GREEN — required recovery verification

```text
$ uv run pytest packages/recovery/tests/test_safe_mode_store.py packages/recovery/tests/test_backup_restore.py -q
............                                                             [100%]
12 passed in 0.21s
```

### Additional scoped verification

```text
$ uv run ruff check packages/recovery/src/rsi_atlas_recovery/safe_mode.py packages/recovery/src/rsi_atlas_recovery/__init__.py packages/recovery/tests/test_safe_mode_store.py packages/recovery/tests/test_backup_restore.py
All checks passed!

$ uv run pytest packages/recovery -q
..............                                                           [100%]
14 passed in 0.17s

$ git diff --check
<no output; success>
```

## Changed Files

- `packages/recovery/src/rsi_atlas_recovery/safe_mode.py`
- `packages/recovery/src/rsi_atlas_recovery/__init__.py`
- `packages/recovery/tests/test_safe_mode_store.py`
- `packages/recovery/tests/test_backup_restore.py`
- `.superpowers/sdd/task-1-report.md`

## Self-Review

- Missing state is the only read case that resolves inactive; malformed JSON,
  symlinks, unsafe permissions, untrusted ownership, wrong type, oversized
  payloads, and descriptor failures all resolve active and fully disabled.
- State writes are complete before replacement and do not follow the existing
  state-file symlink. The same directory descriptor is used for temporary-file
  creation, replacement, and durability sync.
- Existing `SafeModeController()` callers retain their previous in-memory
  behavior, while store-backed controllers reload state on recreation.
- Tests exercise the fixed path, persistence across recreation, state mode,
  each required unsafe-state class, and `require()` behavior through both the
  module and package API.

## Concerns

- Engine-boundary enforcement is deliberately out of scope for this task; it
  remains Task 2's responsibility to call `require()` before each protected
  capability.

## Review-Fix Evidence — 2026-07-20

### Review Findings Addressed

1. Store-backed controllers now refresh from disk in `is_disabled()` and,
   therefore, every `require()` guard boundary. The `state` property remains a
   usable cached snapshot and is updated by a guard refresh or a local change.
2. State-file reads include `O_NONBLOCK`, so a FIFO cannot block a guard path;
   descriptor validation then rejects it as unreadable and resolves active.
3. A directory `fsync` failure after `os.replace` is distinguished from a
   pre-replace write failure. It triggers a best-effort atomic rewrite to the
   fail-closed state, and that returned state becomes the controller state.

### RED — review regressions before the fix

```text
$ uv run pytest packages/recovery/tests/test_safe_mode_store.py -q
........FFF                                                              [100%]
...
E       AssertionError: assert False is True
E       assert True is False
E       assert None is not None
3 failed, 8 passed in 0.37s
```

The failures respectively proved stale guard state, a FIFO-blocked load, and
the post-replace directory-sync exception leaving no coherent exit outcome.

### GREEN — review-fix verification

```text
$ uv run pytest packages/recovery/tests/test_safe_mode_store.py packages/recovery/tests/test_backup_restore.py -q
...............                                                          [100%]
15 passed in 0.18s

$ uv run ruff check packages/recovery/src/rsi_atlas_recovery/safe_mode.py packages/recovery/tests/test_safe_mode_store.py
All checks passed!

$ uv run pytest packages/recovery -q
.................                                                        [100%]
17 passed in 0.17s

$ git diff --check
<no output; success>
```

### Review-Fix Self-Review

- A live controller no longer authorizes a capability based solely on the
  constructor snapshot when it has a store; every capability predicate reloads
  and updates that snapshot.
- `O_NONBLOCK` prevents FIFO deadlock before the regular-file check. The
  regression uses a real FIFO and a bounded daemon thread so the pre-fix test
  fails promptly instead of hanging the test runner.
- The post-replace path returns a fail-closed `SafeModeState` even though the
  requested exit was inactive. Its deterministic test verifies the controller
  and a fresh store load are both active after the recovery rewrite.

## Second Review Fix — 2026-07-20

### Failure Closed

The earlier recovery rewrite could itself fail with ENOSPC after the inactive
primary state had replaced the active one. Its exception was suppressed and a
fresh store then read inactive. That was a fail-open double-failure path.

### Transition Design

- `SafeModeStore.exit()` first creates, file-syncs, and directory-syncs the
  fixed owner-private `safe-mode.exit-guard` marker beside the primary state.
- Any present or unreadable guard marker makes `load()` resolve to active Safe
  Mode. This check is descriptor-safe and non-blocking.
- Only after the marker is durable does exit replace and directory-sync the
  inactive primary state. A failure at that point leaves the already-durable
  marker in place; no recovery temporary state allocation is attempted.
- The marker is removed only after the inactive primary state has synced. If
  marker cleanup errors, loading decides from the marker when it remains; if
  removal was already visible, the previously directory-synced inactive state
  is the durable result.

### RED — ENOSPC double-failure regression

```text
$ uv run pytest packages/recovery/tests/test_safe_mode_store.py -q
...........F                                                             [100%]
...
E       AssertionError: assert False is True
E        +  where False = SafeModeState(active=False, ...).active
1 failed, 11 passed in 0.19s
```

The test injected a directory `fsync` failure immediately after the inactive
replacement, then ENOSPC on any recovery temporary-state open. The controller
returned active, but a fresh store read inactive.

### GREEN — guard-marker verification

```text
$ uv run pytest packages/recovery/tests/test_safe_mode_store.py packages/recovery/tests/test_backup_restore.py -q
................                                                         [100%]
16 passed in 0.17s

$ uv run ruff check packages/recovery/src/rsi_atlas_recovery/safe_mode.py packages/recovery/tests/test_safe_mode_store.py
All checks passed!

$ uv run pytest packages/recovery -q
..................                                                       [100%]
18 passed in 0.16s

$ git diff --check
<no output; success>
```

### Second Review Self-Review

- The double-failure regression observes the real primary replacement, fails
  that directory sync once, and arms ENOSPC for any later `.safe-mode-*`
  allocation. It proves a fresh store and `controller.require(MODELS)` stay
  blocked and asserts no recovery temporary file is attempted.
- All direct inactive `SafeModeStore.save()` calls route through the guarded
  exit transition, preventing callers from bypassing the marker protocol.

## Final Review Fix — 2026-07-20

### Findings Addressed

1. Explicit exit now atomically replaces the fixed guard marker before every
   attempt. A valid, malformed, symlinked, or nonregular stranded marker is
   therefore reconciled descriptor-relatively rather than permanently blocking
   an authenticated retry.
2. `load()` checks the guard before opening state and again after it has read
   and validated that state. A guard installed during the read resolves active
   Safe Mode instead of returning the now-stale inactive state.

### RED — retry and TOCTOU regressions

```text
$ uv run pytest packages/recovery/tests/test_safe_mode_store.py -q
............FF                                                           [100%]
...
E       AssertionError: assert True is False
E       AssertionError: assert False is True
2 failed, 12 passed in 0.19s
```

The first failure left a durable guard through a transient inactive-sync
failure, restored the filesystem, and showed retry remained active. The second
created a marker inside the state-read seam and showed `load()` returned
inactive after only its original guard check.

### GREEN — final review verification

```text
$ uv run pytest packages/recovery/tests/test_safe_mode_store.py packages/recovery/tests/test_backup_restore.py -q
..................                                                       [100%]
18 passed in 0.17s

$ uv run ruff check packages/recovery/src/rsi_atlas_recovery/safe_mode.py packages/recovery/tests/test_safe_mode_store.py
All checks passed!

$ uv run pytest packages/recovery -q
....................                                                     [100%]
20 passed in 0.18s

$ git diff --check
<no output; success>
```

### Final Review Self-Review

- Guard creation writes and syncs a fresh owner-private temporary marker, then
  atomically replaces the fixed marker by directory descriptor. This safely
  reconciles old symlinks and nonregular markers without any marker-absent
  transition window.
- The post-validation guard recheck makes the read operation linearize before
  a newly-created guard or fail closed when that guard is already visible.
- The retry regression proves a fresh controller can complete inactive-state
  persistence and marker removal after the original filesystem failure is
  gone; the TOCTOU regression creates the marker after state bytes are read and
  verifies inactive is not returned.
