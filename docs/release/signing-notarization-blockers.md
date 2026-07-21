# Signing and notarization blockers

Status: **repo-ready and runtime-proven; blocked:external for publication**. A self-contained,
unsigned direct-download candidate and usable Developer ID Application identity exist locally.
`release_ready` remains `false` until the exact candidate is signed, accepted by Apple notarization,
stapled, Gatekeeper-assessed, and clean-user launched.

| Gate class | Remaining blocker | Required closure evidence |
| --- | --- | --- |
| Repository | Closed locally: embedded CPython, engine launcher, PostgreSQL, pgvector, relocated native dependencies, explicit runtime resources, app lifecycle supervision, and artifact-derived inventory are assembled and checked. | Exact-head regression and PR review must remain green. |
| Owner | `Developer ID Application: Rafal Sikora (2NY8A789TN)` is installed with its private key. Apple notary API credentials remain owner-controlled and absent. | Supply the private `.p8` path, key ID, and issuer locally without committing them. |
| External | Apple notarization, Gatekeeper clean-user launch, and GitHub-hosted CI execution are external outcomes. Hosted Actions currently fail before jobs start because of the account billing/spending state. | Accepted notary record, stapled ticket, exact archive/provenance hashes, clean-user launch, and restored hosted CI execution. |

## What is implemented without secrets

| Check | Command / artifact | Honesty |
| --- | --- | --- |
| Fail-closed release gate | `uv run python script/release_check.py --require-release` | Verifies the embedded artifact inventory but stays `release_ready=false` until signing/notarization evidence exists |
| Artifact inventory | `dist/RSIAtlas.app/Contents/Resources/sbom.cdx.json` | Pre-sign inventory of every non-self-referential file plus installed Python, CPython, PostgreSQL, pgvector, native-provider hashes, and license evidence; regenerated for each assembly |
| Entitlement matrix | `docs/release/entitlement-matrix.md` | Draft; includes Unix domain IPC policy |
| Native assembler | `script/assemble_release_app.py --runtime-payload dist/runtime-payload --build-number <positive integer>` | Atomically stages the native app, exact runtime resources, artifact inventory, executable hash, and live dependency-closure result |
| Runtime preflight | `script/check_release_runtime.py --bundle dist/RSIAtlas.app` | Verifies entrypoints, resources, no symlinks, and every live Mach-O load in the staged candidate |
| Runtime smoke | launch the staged app, wait for authenticated status, then quit normally | Proved app-managed database/engine readiness and clean PostgreSQL shutdown locally; this is unsigned runtime evidence |
| Nested signing workflow | `script/sign_and_notarize.sh` | Refuses dirty tracked state or missing credentials, signs inside-out, requires `Accepted`, staples, assesses, archives, and emits external signed-release provenance |

## Local release inputs

```bash
export RSI_ATLAS_SIGNING_IDENTITY="Developer ID Application: Rafal Sikora (2NY8A789TN)"
export RSI_ATLAS_NOTARY_KEY="/path/to/AuthKey_XXXX.p8"
export RSI_ATLAS_NOTARY_KEY_ID="XXXX"
export RSI_ATLAS_NOTARY_ISSUER="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

The signing identity is not a secret and does not need to be downloaded again. The matching private
key is already present in the local keychain. A public certificate download cannot reconstruct a
missing private key, and App Store `Apple Distribution` credentials are not interchangeable with
the Developer ID identity used for this direct-download route.

The signing workflow submits a temporary archive, requires
an `Accepted` notary result, staples and validates the app, runs Gatekeeper assessment, recreates
the final `RSIAtlas-<version>-macOS.zip`, and writes its SHA-256. Until the repository, owner, and
external gates above close **and** those steps pass for the exact staged `.app`,
the release stays **blocked:external**.

## Not claimed

- Developer ID nested signing of the exact embedded runtime
- Notarization stapling
- Gatekeeper clean-user install
- Hardened runtime entitlement audit of a signed artifact
