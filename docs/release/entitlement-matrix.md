# Release entitlement matrix (development inventory)

Status: **repository-reviewed / unsigned** — the staged runtime is proven locally, but this is not
signed-artifact, notarization, or Gatekeeper evidence.

| Capability | Development | Release target | Blocker |
| --- | --- | --- | --- |
| Engine IPC | loopback TCP only with `RSI_ATLAS_ALLOW_LOOPBACK_TCP=1` | app-supervised authenticated Unix domain socket; no TCP release API (crit. 114) | Signed-artifact verification remains |
| Network egress | deny by default | deny + explicit collector allowlist | none for offline |
| Keychain access | denied in Seatbelt worker | Keychain-wrapped backup keys | Apple secrets / Keychain design |
| File-key backup | `file_key_aes_gcm` owner key 0600 | keep as Keychain alternative | none |
| Developer ID signing | unsigned staged `.app` | required | installed identity is usable; exact nested-sign run remains |
| Notarization / stapling | blocked | required | private notary API key, key ID, and issuer are absent |
| Embedded Python / PostgreSQL | packaged and runtime-smoked | nested signed runtime required | exact signed-artifact verification remains |
| Hardened runtime / entitlements | unsigned local candidate | nested hardened-runtime signing with no network entitlement | notary credentials and exact sign run |

## IPC policy (criterion 114)

- Release: the native app starts `RSIAtlasEngine serve --release-ipc`, which binds
  `$DATA_ROOT/ipc/engine.sock` (owner-private) with token authentication and supervises shutdown.
- Development/tests: `RSI_ATLAS_ALLOW_LOOPBACK_TCP=1` may bind `127.0.0.1` only; forbidden when release IPC is set.
- Presence of this document is not Gatekeeper or notarization evidence.

This file exists so `release_check.py` can detect an entitlement matrix document. Presence does
**not** mean the matrix is production-complete or that signing is proven.
