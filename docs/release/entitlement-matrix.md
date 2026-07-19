# Release entitlement matrix (development inventory)

Status: **draft / unsigned** — not Gatekeeper evidence.

| Capability | Development | Release target | Blocker |
| --- | --- | --- | --- |
| Loopback HTTP engine | allowed | replace with authenticated Unix/XPC | release IPC |
| Network egress | deny by default | deny + explicit collector allowlist | none for offline |
| Keychain access | denied in Seatbelt worker | Keychain-wrapped backup keys | Apple secrets / Keychain design |
| File-key backup | `file_key_aes_gcm` owner key 0600 | keep as Keychain alternative | none |
| Developer ID signing | unsigned staged `.app` | required | `RSI_ATLAS_SIGNING_IDENTITY` |
| Notarization / stapling | blocked | required | `RSI_ATLAS_NOTARY_KEY` |
| Embedded signed Python | not packaged | required | packaging milestone |

This file exists so `release_check.py` can detect an entitlement matrix document. Presence does
**not** mean the matrix is production-complete or that signing is proven.
