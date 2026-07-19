# Release entitlement matrix (development inventory)

Status: **draft / unsigned** — not Gatekeeper evidence.

| Capability | Development | Release target | Blocker |
| --- | --- | --- | --- |
| Engine IPC | loopback TCP only with `RSI_ATLAS_ALLOW_LOOPBACK_TCP=1` | authenticated Unix domain socket (`script/run_engine.py --release-ipc`); no TCP release API (crit. 114) | Native Swift UDS client shipped; XPC control channel later; Apple signing/notarization remain |
| Network egress | deny by default | deny + explicit collector allowlist | none for offline |
| Keychain access | denied in Seatbelt worker | Keychain-wrapped backup keys | Apple secrets / Keychain design |
| File-key backup | `file_key_aes_gcm` owner key 0600 | keep as Keychain alternative | none |
| Developer ID signing | unsigned staged `.app` | required | `RSI_ATLAS_SIGNING_IDENTITY` |
| Notarization / stapling | blocked | required | `RSI_ATLAS_NOTARY_KEY` |
| Embedded signed Python | not packaged | required | packaging milestone |
| Hardened runtime / entitlements | unsigned local debug | exact reviewed matrix + nested sign | signing secrets |

## IPC policy (criterion 114)

- Release: `RSI_ATLAS_RELEASE_IPC=1` → bind `$DATA_ROOT/ipc/engine.sock` (owner-private) + token auth.
- Development/tests: `RSI_ATLAS_ALLOW_LOOPBACK_TCP=1` may bind `127.0.0.1` only; forbidden when release IPC is set.
- Presence of this document is not Gatekeeper or notarization evidence.

This file exists so `release_check.py` can detect an entitlement matrix document. Presence does
**not** mean the matrix is production-complete or that signing is proven.
