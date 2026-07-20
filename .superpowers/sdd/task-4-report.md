# Task 4 — Runtime And Repository Truth Reconciliation

## Scope and authority

Updated only the Task 4 runtime presentation, model-boundary copy, tests, readiness documents,
security contact, and deterministic CI surfaces. No acceptance criterion moved to `Proven`; no
package, signing, notarization, clean-install, external credential, release, push, or other external
action was performed.

## RED evidence

The new assertions were added before the presentation/runtime implementation changed.

```text
uv run pytest services/engine/tests/test_runtime.py -q
1 failed, 19 passed, 3 skipped

AssertionError: 'No qualified local model or provider is available in Phase 1.'
    != 'No production-qualified local model or provider is active.'

swift test --package-path apps/macos --filter RuntimePresentationTests
error: cannot find 'RuntimePresentationCopy' in scope
```

These failures proved that the stale runtime summary existed and that the Swift presentation copy
had not yet been made a testable contract.

## Implemented truth surfaces

- Command Center now states: `Local runtime health, integrity, privacy, and resource evidence. This
  is not production or release readiness.` The model line names the production-qualified boundary
  and says development candidates cannot close production acceptance.
- Runtime diagnostics now report `No production-qualified local model or provider is active.` and
  give the governed-evaluation/owner-approval remediation. The stale `Phase 1` model copy and
  runtime-probe error wording are removed.
- `docs/production-plan.md` now describes the current local development state, authenticated
  Unix-domain IPC default, opt-in development TCP, current native destinations/state ownership,
  release-IPC limitation, current entitlement-matrix status, and remaining package/signing gates.
- The old full-delivery roadmap is explicitly a historical evidence ledger. The production plan and
  acceptance matrix record the exact-head reviewer evidence at `18275db`: `1225 passed, 1 skipped`,
  `50` Swift tests passed, product built, and lock/Ruff/strict-mypy/parser governance passed. This
  is development-complete / partially runtime-proven evidence only; all acceptance rows remain
  `Not proven`.
- Signing/notarization is classified as mixed repository, owner, and external gates. `SECURITY.md`
  now directs reports to [info@rsitech.ai](mailto:info@rsitech.ai).
- CI pins `UV_PYTHON` to `3.12`, expands Ruff to `packages services infra script tests`, verifies
  PDF parser governance, and on macOS syncs the uv workspace before all `infra/security/tests` and
  Swift package/product checks. The workflow comments retain the full-PostgreSQL and signed-release
  gaps.

## GREEN verification

```text
uv run pytest services/engine/tests/test_runtime.py -q
20 passed, 3 skipped

swift test --package-path apps/macos --filter RuntimePresentationTests
4 tests passed

uv run pytest -q infra/security/tests
7 passed

ruby -e 'require "yaml"; YAML.load_file(".github/workflows/ci.yml")'
PASS

uv run ruff check packages services infra script tests
All checks passed

uv run python script/audit_pdf_parser_dependencies.py verify
verified docs/dependency-governance/pdf-parser-candidates.json

git diff --check
PASS
```

The host Ruby is 2.6 and rejects the newer `aliases: true` keyword used in the plan's example;
the equivalent compatible `YAML.load_file` invocation parsed the CI file successfully. The required
stale-copy search has two literal matches in the immutable active Task 4 plan itself (its stated
before/after requirement and command); excluding only that non-product instruction file yields no
matches in the changed product, runtime, security, or readiness surfaces.

## Remaining limitations

The focused checks above do not repeat the historical exact-head full regression and do not prove a
production runtime, staged package, Developer ID signing, notarization, Gatekeeper clean install,
or acceptance completion. The current CI intentionally still excludes full Unix-socket PostgreSQL
integration and owner-controlled signed-release work.

## Review follow-up: shared status-payload consistency

A final review found that the Swift `system_status_v1_1` fixture and the Python diagnostics/CLI
test fixtures still carried the pre-Task-4 model summary/remediation. Test-first updates produced
the expected RED failures in the diagnostics fixture and Swift decoder; after updating the shared
payload and direct consumers, the relevant engine suite reported **36 passed, 3 skipped** and the
full Swift package suite reported **51 tests passed**. The full direct sweep also found and updated
the stale CLI doctor-output assertion.

The Ubuntu `python-unit` CI selection now explicitly includes the non-PostgreSQL
`services/engine/tests/test_runtime.py`, `test_diagnostics.py`, and `test_cli.py`, so the runtime
copy, diagnostics fixtures, and doctor presentation cannot silently regress while the broader
PostgreSQL integration suite remains intentionally separate. The stale-copy scan, excluding only
the immutable active Task 4 plan that documents the search itself, reports no matches.
