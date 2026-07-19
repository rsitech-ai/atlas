# Must-have / partial closure plan (2026-07-19)

Drive toward design-complete without Apple Developer secrets. Honesty rule: never mark
acceptance-matrix rows `Proven` without runnable evidence.

## Ordered slices

1. Sealed PRODUCTION promotion gates (embedding/reranker/parser/chunk) + offline fixtures
2. Release IPC: authenticated Unix-domain socket; TCP only behind explicit test flag
3. Signing/notarization fail-closed hardening + blocker doc
4. Multi-specialist orchestration without LangGraph + Report Studio contracts/minimal UI
5. Live collectors deepen (allowlist HTTPS, reorg, WS fail-closed honesty)
6. Calibrated OSS/heuristic monitoring triage + calibration harness
7. Local models load/unload/OOM + Foundation Models unavailable honesty
8. Codex gate harden; recovery restore/Safe Mode/upgrade scripts
9. Partials: injection suite, comparison matrix UI, OTel Swift→publication where possible
10. Acceptance matrix + production-plan honesty update

## Hard blockers expected

- Apple Developer ID signing / notarization / stapling / Gatekeeper clean-user
- Keychain wrap UI flow (if entitlement/signing blocked)
- Live Codex App Server qualification (needs Codex binary + isolated worktree proof)
- Docling (license/offline still blocked)
- Sealed holdout `PRODUCTION` claim for real models (needs owner-sealed corpus beyond synthetic fixtures)
