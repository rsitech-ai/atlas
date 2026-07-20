# Signing and notarization blockers

Status: **blocked: mixed repository, owner, and external gates** — local fail-closed paths exist,
but `release_ready` remains `false`. No development regression result is package, signing,
notarization, or clean-install evidence.

| Gate class | Remaining blocker | Required closure evidence |
| --- | --- | --- |
| Repository | Staged release packaging must include the embedded runtime, reviewed entitlements, and nested-sign inventory. | Reproducible staged artifact and checked release-assembly records. |
| Owner | Developer ID identity and Apple notary API credentials are owner-controlled and absent. | Owner supplies the required secrets locally without committing them. |
| External | Apple notarization processing and a clean-user Gatekeeper install are external/runtime outcomes. | Stapled notarization record and clean-machine install evidence for the exact signed `.app`. |

## What is implemented without secrets

| Check | Command / artifact | Honesty |
| --- | --- | --- |
| Unsigned inventory | `uv run python script/release_check.py --require-release` | Always `release_ready=false` |
| SBOM from lock | `dist/sbom.cdx.json` via release check | Generated; not Gatekeeper evidence |
| Entitlement matrix | `docs/release/entitlement-matrix.md` | Draft; includes Unix domain IPC policy |
| Packaging helper | `script/package_release.sh` | Stages + runs checks; refuses to claim notarized |
| Nested-sign stub | `script/sign_and_notarize.sh` | Fail-closed without `RSI_ATLAS_SIGNING_IDENTITY` / `RSI_ATLAS_NOTARY_KEY` |

## Secrets the owner must provide

```bash
export RSI_ATLAS_SIGNING_IDENTITY="Developer ID Application: … (TEAMID)"
export RSI_ATLAS_NOTARY_KEY="/path/to/AuthKey_XXXX.p8"
export RSI_ATLAS_NOTARY_KEY_ID="XXXX"
export RSI_ATLAS_NOTARY_ISSUER="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

Until the repository, owner, and external gates above close **and**
`script/sign_and_notarize.sh` records stapled notarization output for the exact staged `.app`,
criteria 112–134 stay **Not proven**.

## Not claimed

- Developer ID nested signing of embedded Python/runtime
- Notarization stapling
- Gatekeeper clean-user install
- Hardened runtime entitlement audit of a signed artifact
