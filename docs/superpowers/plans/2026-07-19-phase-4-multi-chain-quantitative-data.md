# Phase 4 Multi-Chain / Quantitative Data Implementation Plan

> **Execution:** Follow repository TDD and review gates task by task. Do not claim Section 33
> criteria 43–44 or 61–81 closed. Do not begin Phase 5 monitoring until every Phase 4 acceptance
> item below is either proven or explicitly left as development-only. Do not promote live RPC,
> WebSocket, Bitcoin Core, DuckDB, or Parquet providers without governance.

**Goal:** From offline/fixture sources only, admit Bitcoin / EVM / Solana / market / governance /
GitHub raw envelopes into immutable bitemporal observations with quality quarantine, pinned chain
identity, exact market precision, leakage-safe feature eligibility, and non-trading research
signals—without live network collection or production analytics backends.

**User-visible outcome:** Development loopback APIs import fixture collector batches, persist raw
envelopes + normalized observations, expose point-in-time inspection, compute a minimal feature
value only when `available_time <= as_of`, and emit research signals that cannot trade.

**Architecture:** Keep Phases 1–3 immutable. Phase 4 adds (1) strict observation/collector
contracts, (2) shared offline collector pipeline (raw → normalize → quality → publish/quarantine),
(3) chain-family fixture adapters with pinned identity + reorg/orphan stubs, (4) market /
governance / GitHub fixture adapters, (5) PostgreSQL observation persistence (migration `0010`),
(6) minimal feature + signal services. Live/monitored collectors and DuckDB/Parquet remain
fail-closed stubs without new dependencies (`ponytail:` upgrade = governed providers later).

**Tech Stack:** Python 3.11+, Pydantic strict contracts, Psycopg 3, PostgreSQL 17, existing CAS
artifact store, pytest + real test DB. **No new third-party dependency.** Decimal for money.
Fixture JSON only—no live RPC/HTTP.

## Global Constraints

1. Collection is watchlist/fixture-scoped; no global archive pretence.
2. Every provider payload persists as an immutable raw envelope **before** decode.
3. No published “latest” without a pinned chain reference (EVM/Solana/Bitcoin identity).
4. Financial amounts use `Decimal` / fixed-scale strings—never binary float.
5. Invalid data quarantines with reasons; it is not silently dropped.
6. Features are eligible only when `feature.available_time <= investigation.as_of`.
7. Research signals cannot place trades, sign transactions, or access exchange accounts.
8. Live/monitored acquisition modes fail closed (`blocked_live_network` / policy denial).
9. DuckDB and Parquet remain `blocked_dependency` stubs—no new deps in this slice.
10. Acceptance-matrix rows get **development partial** evidence only; no false criterion closure.
11. Failures are typed and sanitized; raw payloads never enter HTTP error bodies.

## Development-slice acceptance (must prove)

1. Strict contracts reject invalid envelopes, collector defs, observations, pins, instruments,
   governance/GitHub records, features, and trading-capable signals.
2. Offline fixture import for Bitcoin, EVM, Solana, market, governance, and GitHub shares one
   downstream observation contract.
3. Raw envelopes are content-addressed and immutable before normalization.
4. Pinned identity required: EVM `chain_id+block+hash`, Solana `cluster+slot+blockhash+commitment`,
   Bitcoin `network+height+hash`.
5. Quality failures quarantine with reasons; conflicted provider disagreement is explicit.
6. Reorg/orphan stub marks affected Bitcoin/EVM observations orphaned and retains history.
7. Market fixture uses exact decimal precision; gap/sequence failure forces resnapshot path.
8. Governance on-chain execution links to off-chain proposal identity when both present.
9. GitHub fixture respects cursor + rate-limit metadata (no live fetch).
10. Point-in-time observation query respects valid/system time (bitemporal read).
11. Minimal feature computation refuses leakage (`available_time > as_of`).
12. Research signal schema forbids trading/signing/exchange fields.
13. Loopback APIs expose fixture import + observation inspect without claiming live monitors.
14. Live collector stubs and DuckDB/Parquet stubs fail closed without new dependencies.

## Explicitly out of scope (blocked / later)

- Live Bitcoin Core RPC, EVM/Solana RPC/indexers, market WebSockets, GitHub HTTP
- Production DuckDB/Parquet writers (fail-closed stub only)
- Full detector roster, protocol metric methodology registry beyond fixtures
- Due-diligence dossiers / cross-ecosystem comparison UX (criteria 43–44 remain open)
- Continuous monitoring, alerts, research invalidation (Phase 5)
- Criteria 61–81 closed; multi-ecosystem native comparison matrix

---

## File structure

- `packages/contracts/src/rsi_atlas_contracts/observations.py` — envelopes, collectors, pins,
  observations, market/gov/github payloads, features, signals
- `packages/contracts/tests/test_observations.py`
- `packages/collectors/` — offline pipeline, fixture adapters, fail-closed live stubs, quality,
  features, signals
- `packages/collectors/fixtures/` — Bitcoin/EVM/Solana/market/governance/GitHub JSON fixtures
- `migrations/0010_structured_observations.sql`
- `packages/storage/.../observation_repository.py`
- `services/engine/...` — loopback collector import + observation APIs
- README / production-plan / roadmap / acceptance-matrix — honest partial evidence only

---

### Task 1: Strict observation + collector contracts

**Files:**

- Create: `packages/contracts/src/rsi_atlas_contracts/observations.py`
- Modify: `packages/contracts/src/rsi_atlas_contracts/__init__.py`
- Create: `packages/contracts/tests/test_observations.py`

**Interfaces (minimum):**

- `SourceFamily`, `AcquisitionMode`, `CollectorLifecycle`, `CollectorDefinition`
- `RawEnvelope`, `raw_envelope_id`
- `EvmPin`, `SolanaPin`, `BitcoinPin`, `ChainPin`
- `FinalityState`, `SolanaCommitment`, `ProviderQualityState`, `ObservationQuality`
- `ObservationHeader`, `Observation`, `QuarantineRecord`
- `InstrumentIdentity`, `MarketTick`, `GovernanceRecord`, `GitHubRecord`
- `FeatureDefinition`, `FeatureValue`, `ResearchSignal` (no trade capability)
- `AnalyticsBackendStatus` (`blocked_dependency` for duckdb/parquet)

- [x] **Step 1: Write RED contract tests**
- [x] **Step 2: Run RED**
- [x] **Step 3: Implement smallest strict models**
- [x] **Step 4: Verify and commit**

```bash
uv run pytest packages/contracts/tests/test_observations.py -q
uv run ruff check packages/contracts && uv run ruff format --check packages/contracts
uv run mypy packages/contracts/src
git commit -m "feat: define structured observation and collector contracts"
```

---

### Task 2: Offline collector pipeline + fixture adapters

**Files:**

- Create: `packages/collectors/` workspace package
- Create: `packages/collectors/src/rsi_atlas_collectors/{pipeline,quality,bitcoin,evm,solana,market,governance,github,live_stubs,analytics_stubs}.py`
- Create: `packages/collectors/fixtures/*.json`
- Create: `packages/collectors/tests/test_*.py`
- Modify: root `pyproject.toml` workspace members

- [x] **Step 1: RED** — fixture import yields envelope + observation; live modes raise typed block
- [x] **Step 2: Implement offline adapters + shared pipeline**
- [x] **Step 3: GREEN + commit**

```bash
uv run pytest packages/collectors/tests -q
git commit -m "feat: add offline fixture collectors with fail-closed live stubs"
```

---

### Task 3: Observation persistence (migration 0010)

**Files:**

- Create: `migrations/0010_structured_observations.sql`
- Create: `packages/storage/src/rsi_atlas_storage/observation_repository.py`
- Create: `packages/storage/tests/test_observation_repository.py`

- [x] **Step 1: RED** — persist envelope/observation; bitemporal as-of read; quarantine row
- [x] **Step 2: Migration + repository**
- [x] **Step 3: GREEN + commit**

```bash
uv run pytest packages/storage/tests/test_observation_repository.py -q
git commit -m "feat: persist bitemporal observations and raw envelopes"
```

---

### Task 4: Features, signals, reorg stub

**Files:**

- Create: `packages/collectors/src/rsi_atlas_collectors/features.py`
- Create: `packages/collectors/src/rsi_atlas_collectors/signals.py`
- Create: `packages/collectors/src/rsi_atlas_collectors/reorg.py`
- Create: `packages/collectors/tests/test_features.py`, `test_signals.py`, `test_reorg.py`

- [x] **Step 1: RED** — leakage refusal; signal no-trade; orphan preserves history
- [x] **Step 2: Implement**
- [x] **Step 3: GREEN + commit**

> Features/signals/reorg landed inside the collectors package commit with Task 2 tests
> (`test_feature_*`, `test_reorg_*`, `test_analytics_*`).

```bash
uv run pytest packages/collectors/tests/test_features.py packages/collectors/tests/test_signals.py packages/collectors/tests/test_reorg.py -q
git commit -m "feat: add leakage-safe features, non-trading signals, reorg orphan stub"
```

---

### Task 5: Loopback collector / observation APIs

**Files:**

- Modify: `services/engine/src/rsi_atlas_engine/api.py`, `runtime.py` (or equivalent wiring)
- Create: `services/engine/tests/test_collectors_api.py`

- [x] **Step 1: RED** — import fixture + list observations over loopback
- [x] **Step 2: Wire service**
- [x] **Step 3: GREEN + commit**

```bash
uv run pytest services/engine/tests/test_collectors_api.py -q
git commit -m "feat: expose fixture collector and observation loopback APIs"
```

---

### Task 6: Honest docs + Phase 4 slice close

**Files:**

- Modify: `README.md`, `docs/production-plan.md`, `docs/acceptance-matrix.md`,
  `docs/superpowers/plans/2026-07-18-full-product-delivery-roadmap.md`,
  this plan (checkboxes)

- [x] **Step 1: Update evidence language (development partial only)**
- [x] **Step 2: Full focused verification**
- [x] **Step 3: Commit close**

```bash
uv run pytest packages/contracts/tests/test_observations.py packages/collectors/tests packages/storage/tests/test_observation_repository.py services/engine/tests/test_collectors_api.py -q
uv run ruff check packages/contracts packages/collectors packages/storage services/engine
uv run mypy packages/contracts/src packages/collectors/src
git commit -m "docs: close Phase 4 multi-chain quantitative development slice"
```

---

## Self-review

1. **Spec coverage (§§19–23):** collector contract, raw envelope, three chain families, market
   precision, governance/GitHub, bitemporal quality, features/signals, fail-closed analytics —
   each has a task. Live providers and DuckDB/Parquet production remain explicit stubs.
2. **No placeholders:** tasks name files, interfaces, and commands.
3. **Type consistency:** `RawEnvelope` → `Observation` → `FeatureValue` / `ResearchSignal` share
   `observation_id` / subject / as-of fields across tasks.
