# Embedded runtime closure reflection

## Task

- **ID / title:** RSI Atlas embedded runtime and direct-download release closure
- **Date:** 2026-07-21
- **Scope:** Self-contained ARM64 runtime, native app lifecycle, artifact inventory, and release gates.
- **Authority boundary:** Local code, tests, public PR, and merge were authorized. Apple credentials may not be invented or committed; an unnotarized download may not be published.

## Success and Risk

- **Success criteria:** No Homebrew/repository runtime dependency, live Mach-O closure, authenticated app-managed database/engine lifecycle, exact artifact/license inventory, and fail-closed signing.
- **Hypothesis 1:** Copying only the obvious PostgreSQL/pgvector entrypoints would be sufficient.
- **Hypothesis 2:** Relocating the complete recursive native dependency graph and materializing contained symlinks would produce a portable candidate.
- **Hypothesis 3:** Entrypoint/help smokes would be sufficient lifecycle evidence.
- **Rollback path:** Keep public main at PR #2 and publish no artifact if closure, lifecycle, or exact-head gates fail.

## Candidate Directions

| Candidate | Expected benefit | Main risk | Evidence before choice | Decision |
|---|---|---|---|---|
| Copy entrypoints and flatten dylibs | Small payload and simple builder | Basename collisions, broken loader context, undeclared transitive dependencies | Homebrew binaries exposed absolute and `@rpath` dependency chains | Rejected |
| Preserve provider/version-relative native trees and rewrite every live load | Deterministic closure with provider provenance and licenses | More relocation/signing complexity | Live `otool` graph and isolated launch smokes | Retained |
| Treat engine help as launch proof | Fast preflight | Misses database startup, token/socket race, and cleanup failures | SIGTERM experiment left PostgreSQL cleanup uncertain | Rejected |
| Supervise the release engine from Swift and prove normal app quit | User-visible lifecycle evidence | Shutdown escalation must not orphan children | Authenticated readiness and AppleScript quit removed the postmaster PID | Retained |

## Evidence

- **First meaningful failure signal:** Native entrypoints existed but transitive Mach-O loads still resolved to Homebrew paths; later, engine termination did not initially prove PostgreSQL cleanup.
- **Commands or runtime checks:** Focused release tests; live closure scan; isolated CPython/PostgreSQL/pgvector smoke; authenticated UDS status; staged app launch and normal quit; artifact-inventory rebuild and mutation test.
- **What the evidence ruled in or out:** Entrypoint presence, hard-coded closure flags, help-only smokes, and a lock-universe SBOM are insufficient release evidence.

## Decision

- **Root cause or remaining unknown:** Packaging originally modeled named files rather than the runtime dependency/lifecycle graph. Apple notarization and clean-user behavior remain unknown until owner credentials are supplied.
- **Retained fix / direction:** Preserve native provider structure, recompute closure live, make resources explicit, supervise engine/database lifecycle in the app, and derive the embedded inventory from the staged pre-sign artifact.
- **Why alternatives were rejected:** Flattening lost loader/provider identity; copying `.venv` included editable/dev state; embedding post-sign provenance would invalidate the signature it describes.
- **Residual risk:** Developer ID nested signing may expose entitlement or hardened-runtime incompatibilities; hosted CI cannot start while billing is blocked.
- **Rollback trigger:** Any unresolved live load, payload mutation, orphaned database, inventory mismatch, non-accepted notarization, Gatekeeper rejection, or exact-head regression failure.

## Reusable Lesson

- **Pattern to retain:** Separate structural presence, live dependency closure, lifecycle behavior, pre-sign inventory, and final signed provenance into distinct evidence gates.
- **Pattern to avoid:** Treating a green build, an entrypoint, or a generated manifest as proof of the runtime state it merely claims.
- **Where it applies next:** Other self-contained macOS apps with embedded interpreters, databases, native plugins, or Developer ID distribution.
