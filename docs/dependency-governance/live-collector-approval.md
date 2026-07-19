# Live collector network approval

Status: **approved** (opt-in monitored HTTPS; deny-by-default)

## Decision

Approved on 2026-07-19 by actor `andrzej:oss-production-ready-instruction`.

Live Bitcoin/EVM/Solana/market/governance/GitHub collectors may perform HTTPS fetches only when:

1. Acquisition mode is an explicit live mode
2. User supplies canonical `https://host:port` origins (no path, no credentials, no baked-in keys)
3. `NetworkPolicy.monitored(allowlisted_origins=...)` authorizes the origin for `atlas-collector`
4. Process capability allowlist matches exactly

Default remains offline fixtures. No API keys in repo. Public OSS RPC patterns only.

### Allowed

- Stdlib `urllib.request` HTTPS GET/POST with timeouts to allowlisted origins
- Envelope `network_policy_decision=allow_monitored` on success; `deny_live` on policy deny

### Not allowed

- Default egress / DNS without allowlist
- Hard-coded Infura/Alchemy/GitHub tokens
- WebSocket streams in this slice (remain fail-closed until separate governance)

### Rollback

Refuse live modes; restore fixture-only `refuse_live_collect`.
