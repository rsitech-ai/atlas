# Security Policy

## Supported versions

This project is early open-source software. Security fixes land on the default branch
when maintainers can reproduce and verify them. There is no long-term support promise yet.

## What this product is (threat model sketch)

RSI Atlas is a **local-first research** tool for Apple Silicon Macs. It is intentionally
**not** a wallet, exchange, custodian, or trading bot. It must not hold private keys for
signing transactions, and collectors deny network egress by default.

Report issues that affect:

- local data confidentiality or integrity (PostgreSQL socket policy, CAS, admissions)
- sandbox / Seatbelt boundaries for the document worker
- injection or path traversal at import / IPC trust boundaries
- secrets leakage in logs, traces, or reproduction bundles
- supply-chain or dependency governance bypasses

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Preferred:

1. Use [GitHub private vulnerability advisories](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability) for this repository (enable “Private vulnerability reporting” in repo settings if it is not on yet).
2. Or email: [info@rsitech.ai](mailto:info@rsitech.ai).

Include:

- affected commit / tag if known
- reproduction steps on a clean clone
- impact assessment (confidentiality / integrity / availability)
- whether you believe secrets or user documents are exposed

Please allow a reasonable window before public disclosure so a fix or mitigation can land.

## Non-vulnerabilities / out of scope (for now)

- Unsigned / un-notarized macOS builds (signing is intentionally blocked without owner Apple secrets; see `docs/release/signing-notarization-blockers.md`)
- Missing Docling / OCR when those paths are fail-closed by design
- Research quality of embeddings or retrieval (candidate models; not sealed PRODUCTION without promotion proof)

## Secrets in this repository

- Do not commit `.env`, Apple notary `.p8` keys, Keychain material, or live API tokens.
- Optional live collectors require **user-supplied** allowlisted origins; no baked-in API keys.
- Signing env vars (`RSI_ATLAS_SIGNING_IDENTITY`, `RSI_ATLAS_NOTARY_*`) are owner-local only.
