# Embedded runtime and closure

## Goal

- User-visible outcome: RSI Atlas can assemble a self-contained Apple Silicon runtime candidate from pinned local inputs and prove whether it is safe to enter Developer ID signing.
- How to see it working: the staged app contains isolated CPython, production-only locked Python packages, a native engine launcher, PostgreSQL 17.10, pgvector 0.8.5, and no unresolved non-system Mach-O dependency; isolated Python/engine/PostgreSQL/pgvector smokes either pass or emit exact blockers.

## Current State

- Relevant paths: `packages/release`, `script/assemble_release_app.py`, `script/check_release_runtime.py`, `script/package_release.sh`, and `script/sign_and_notarize.sh`.
- Existing baseline: public main `7b0a8e9` atomically assembles a versioned native shell and refuses signing because all four runtime entrypoints and dependency closure are absent. This branch closes those repository-local runtime gates; signing/notarization remain downstream.
- Available inputs: uv-managed CPython 3.12.10 arm64, Homebrew PostgreSQL 17.10 arm64, Homebrew pgvector 0.8.5, Xcode/clang, and the lockfile. The production wheel set requires hash-locked registry acquisition; copying `.venv` is prohibited because it contains dev tools and absolute editable paths.
- Constraints: release output must not rely on Homebrew, system Python, user site packages, current working directory, or repo paths. Never weaken signing preflight. Notary credentials remain an owner/external gate.

## Target State

- Desired behavior: build runtime inputs in a temporary directory, copy them only through atomic app assembly, relocate non-system Mach-O dependencies into the app, record exact hashes, run isolated launch smokes, and make signing preflight succeed only when all checks pass live.
- Non-goals: notarization without owner API credentials, model/provider qualification, clean-user UI acceptance, or claiming exact signed-release zero-egress before a signed artifact exists.

## Risks and Failure Modes

- Homebrew binaries contain absolute dylib references; every copied Mach-O must be recursively relocated or closure must remain blocked.
- Python wheels can contain native extensions and dev/editable artifacts; build only the no-dev lock set and reject `.pth`, source-tree paths, pip, pytest, mypy, and Ruff.
- A stale verification file could outlive runtime mutation; live preflight must recompute closure and launch evidence.
- PostgreSQL/pgvector smoke can leave processes or temporary clusters; use a private temporary root and guaranteed fast-stop cleanup.
- Installed wheels contained repository-relative assumptions for operational migrations and the document-worker Seatbelt profile. The release now supplies a validated explicit resource root containing only those operational files; development evaluation/calibration fixtures remain excluded.
- The Swift app now supervises `RSIAtlasEngine`, waits for authenticated readiness, and performs interrupt-first bounded shutdown. Actual staged-app readiness and normal-quit database cleanup are required evidence, not a help-only smoke.
- Semantic versions do not identify immutable uv/Homebrew builds. Record source hashes, receipts, revisions/bottle metadata, dependency graph, wheel hashes, and a clean exact Git tree; refuse dirty/mutable inputs.
- Python/PostgreSQL trees contain internal symlinks and Mach-O variants. Materialize only contained targets, reject loops/special files, and model all dyld load kinds and loader contexts rather than flattening by basename.
- Smokes and signing mutate different parts of an artifact. Force disposable write roots and no bytecode, prove pre/post-smoke tree identity, and keep pre-sign closure evidence separate from final signed provenance.
- The SBOM must describe the shipped tree and redistributed native dependencies/licenses, not merely every name in `uv.lock`.

## Milestones

### M1. Runtime source contract

- Goal: define and test the exact isolated source tree accepted by assembly.
- Files / systems: release module and tests.
- Changes: add typed source layout validation, atomic copying, legal/license inventory, and honest manifest fields.
- Verification: RED then focused release tests.
- Expected result: malformed, symlinked, dev-contaminated, or incomplete source trees fail before replacing an existing bundle.

### M2. Pinned local runtime builder

- Goal: produce a complete source tree without copying the development virtualenv.
- Files / systems: build script, native launcher source, engine `__main__`, script contract tests.
- Changes: copy CPython, build production workspace wheels, install the no-dev lock set, compile launcher, copy PostgreSQL and pgvector files/licenses.
- Verification: isolated imports and entrypoint inspection in a disposable build; recursively reject `.pth`, `.egg-link`, editable `direct_url.json`, absolute shebangs/source paths, dev distributions, external links, and special files.
- Expected result: four structural entrypoints are present and production Python has no editable/dev paths.

### M3. Dependency relocation and live closure

- Goal: remove all Homebrew/user absolute Mach-O references.
- Files / systems: release closure module and builder.
- Changes: recursively copy non-system dylibs while preserving provider-relative trees; model `LC_ID_DYLIB`, weak/re-export/upward loads, ordered `LC_RPATH`, `@loader_path`, `@executable_path`, and `@rpath`; reject collisions and unresolved dependencies; hash the runtime tree.
- Verification: `otool` closure scan over every bundled Mach-O.
- Expected result: only system frameworks/libraries or resolvable in-bundle references remain.

### M4. Isolated launch smokes and package integration

- Goal: prove candidate launch behavior before signing.
- Files / systems: runtime check and package scripts.
- Changes: explicit bundle resource-root contract and resources; isolated Python/engine import smoke; release-native PostgreSQL lifecycle and private temp-cluster/pgvector smoke; mutation-free live preflight JSON; actual Swift app launch/supervision with readiness/token/socket handshake, PID-bound termination, restart cooldown, and app-termination cleanup.
- Verification: build real local candidate, run check twice, then prove signing reaches only the owner credential gate without mutating the unsigned candidate.
- Expected result: repository blockers close or exact launch blocker codes remain; notarization still does not run without credentials.

### M5. Review and PR

- Goal: publish only reviewed code and truthful evidence.
- Files / systems: docs, tests, GitHub PR.
- Changes: full regression, independent review, PR, merge only when clean.
- Verification: `script/codex_full_regression.sh`, real runtime build/smokes, PR diff review.
- Expected result: merged code or a precise HOLD; no unsafe downloadable release.

## Verification

- `uv run pytest packages/release/tests -q`
- `uv run ruff check packages/release script services/engine`
- `uv run ruff format --check packages/release script services/engine`
- `uv run mypy packages/release services/engine script`
- `./script/codex_full_regression.sh`
- Manual smoke: assemble a real runtime candidate, confirm no forbidden Python artifacts/paths, scan all Mach-O dependencies, launch engine help, initialize a private temporary PostgreSQL cluster, and create/query pgvector.

## Decision Log

- 2026-07-20: Build production Python packages from hash-locked requirements and workspace wheels; reject copying `.venv` because it ships dev tools and absolute editable paths.
- 2026-07-20: Treat the installed Homebrew/uv runtimes only as pinned build inputs. The final candidate must contain and resolve its own runtime files.
- 2026-07-20: Keep signing and notarization downstream of live closure and launch checks.
- 2026-07-20: Independent architecture review made resource-root, provenance, complete dyld semantics, artifact-derived SBOM/license coverage, mutation-free verification, release-native PostgreSQL lifecycle, and actual Swift lifecycle supervision mandatory completion gates rather than follow-up polish.
- 2026-07-21: Keep the embedded artifact inventory pre-sign and self-exclude only its own JSON and the assembly manifest. After Apple mutates signatures and stapling state, bind the final archive, notary log, code identity, and exact Git commit/tree in a separate checksummed provenance record.

## Progress Log

- 2026-07-20: Confirmed toolchain versions and sizes; production Python dependency install is 41 packages / about 54 MiB before CPython, and requires hash-locked wheel acquisition.
- 2026-07-20: Runtime payload validation and isolated Python module/native launcher entrypoints are under TDD; the broader architecture review expanded the completion bar before dependency copying begins.
- 2026-07-20: M1/M2 foundation passes 40 release/entrypoint tests: atomic payload copying, recursive path-injection/special-file rejection, isolated module entrypoint, native ARM64 launcher, pinned no-dev wheel build, local tool version checks, Git/tree and source/receipt/wheel provenance, and third-party legal inputs.
- 2026-07-21: M1-M4 implemented. Live closure found 167 Mach-O images / 385 loads with every non-system load resolving in-bundle; isolated Python/PostgreSQL/pgvector, authenticated engine IPC, and normal app quit smokes passed without payload mutation or leaked processes.
- 2026-07-21: Artifact inventory verification passes against the staged app with exact file hashes, installed Python distributions, CPython/PostgreSQL/pgvector, all seven relocated native providers, and no missing license evidence. Release check now reads and verifies the embedded inventory instead of creating an unrelated `dist/sbom.cdx.json`.
- 2026-07-21: The first full regression exposed a pre-existing collector API classification defect: a missing default PostgreSQL socket raised `ValueError` and was reported as invalid client input (422) instead of service unavailable (503). Narrowed the client-error boundary and added missing-fixture coverage; focused reproduction now passes.
- 2026-07-21: Full regression passed at code commit `641f12912700`: 1308 Python tests passed, one optional ONNX test skipped, 55 Swift tests passed, Swift product build passed, and lock/Ruff/format/strict-mypy/parser-governance gates passed.
- 2026-07-21: Final workflow inspection found `package_release.sh` still assembled the obsolete shell-only app. It now builds the pinned runtime payload and passes it explicitly into atomic app assembly before the fail-closed signing/notarization gate; the script contract locks this order and argument.
- 2026-07-21: End-to-end packaging at `0ca11b8f744f` rebuilt a clean exact-SHA payload and app, verified live closure, and stopped only at unsigned/signing-identity/notarization blockers. The actual app then reached authenticated UDS readiness with pgvector 0.8.5 and all 12 migrations, and normal app quit removed the postmaster PID/process. The readiness helper now polls token creation instead of racing app startup.
- 2026-07-21: Next: exact-head full regression, final independent review, PR/merge, then stop at the owner notary-credential gate rather than publishing an unnotarized download.

## Rollback / Recovery

- If this fails: preserve main and PR #2; discard only the new candidate branch after documenting exact blockers.
- Safe fallback: retain the merged shell/preflight foundation and publish no artifact.
