# Signing and notarization blockers

Status: **blocked: mixed repository and external gates** — a usable Developer ID Application
identity is installed locally, but the self-contained release assembly and notarization credentials
are not complete. `release_ready` remains `false`. No development regression result is package,
signing, notarization, or clean-install evidence.

| Gate class | Remaining blocker | Required closure evidence |
| --- | --- | --- |
| Repository | The versioned native shell is reproducibly assembled, but embedded Python, the engine launcher, PostgreSQL, and pgvector are absent. Runtime entrypoint presence alone is not dependency closure or launch proof. | All four fixed paths contain parseable thin ARM64 Mach-O code of the expected executable/library type, every path ancestor is non-symlinked, dependency closure is verified, and isolated launch smokes pass. |
| Owner | `Developer ID Application: Rafal Sikora (2NY8A789TN)` is installed with its private key. Apple notary API credentials remain owner-controlled and absent. | Owner supplies only the notary key reference, key ID, and issuer locally without committing them. |
| External | Apple notarization processing and a clean-user Gatekeeper install are external/runtime outcomes. | Stapled notarization record and clean-machine install evidence for the exact signed `.app`. |

## What is implemented without secrets

| Check | Command / artifact | Honesty |
| --- | --- | --- |
| Unsigned inventory | `uv run python script/release_check.py --require-release` | Always `release_ready=false` |
| SBOM from lock | `dist/sbom.cdx.json` via release check | Generated; not Gatekeeper evidence |
| Entitlement matrix | `docs/release/entitlement-matrix.md` | Draft; includes Unix domain IPC policy |
| Native-shell assembler | `script/assemble_release_app.py --build-number <positive integer>` | Writes version/build metadata, legal files, SBOM, executable hash, and an honesty manifest; does not claim a complete runtime |
| Packaging helper | `script/package_release.sh` | Builds and atomically stages the shell before the fail-closed release check |
| Runtime preflight | `script/check_release_runtime.py --bundle dist/RSIAtlas.app` | Validates non-symlinked thin ARM64 Mach-O entrypoints but always retains `runtime_dependency_closure_unverified`; signing remains blocked in this slice |
| Nested signing workflow | `script/sign_and_notarize.sh` | Signs Mach-O code and nested bundles inside-out with hardened runtime/timestamps only after runtime preflight; workflow is unproven until executed with a complete bundle and owner credentials |

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

After a complete runtime is assembled, the signing workflow submits a temporary archive, requires
an `Accepted` notary result, staples and validates the app, runs Gatekeeper assessment, recreates
the final `RSIAtlas-<version>-macOS.zip`, and writes its SHA-256. Until the repository, owner, and
external gates above close **and** those steps pass for the exact staged `.app`,
criteria 112–134 stay **Not proven**.

## Not claimed

- Developer ID nested signing of embedded Python/runtime
- Notarization stapling
- Gatekeeper clean-user install
- Hardened runtime entitlement audit of a signed artifact
