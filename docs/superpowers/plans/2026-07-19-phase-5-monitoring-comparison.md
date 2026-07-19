# Phase 5 Monitoring and Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [x]`) syntax for tracking.
>
> **Execution:** Follow repository TDD and review gates task by task. Do not claim Section 33
> criteria 45, 61, or 82–84 closed. Do not begin Phase 6 evaluation/release until every Phase 5
> acceptance item below is either proven or explicitly left as development-only. Do not enable
> live collectors, calibrated semantic triage LLMs, or native timeline UI completeness in this
> slice.

**Goal:** From a published observation/feature change (Phase 4 fixtures), run deterministic
materiality detection, deduplicate alerts, invalidate affected research, launch a targeted
research stub, and surface the change on a cross-chain timeline / comparison matrix—without live
trading, unsigned release, LangGraph durability, or incomplete Phase 4 live collectors.

**User-visible outcome:** Development loopback APIs evaluate a previous→current observation pair
against monitoring rules, emit a deduplicated alert with append-only lifecycle events, record
research invalidation when inputs are orphaned/quarantined, return a targeted-research launch
stub (plan-validated, no graph run), and expose comparison-matrix / timeline payloads that link
back to raw envelope / observation IDs.

**Architecture:** Keep Phases 1–4 immutable. Phase 5 adds (1) strict monitoring/comparison
contracts, (2) deterministic change detectors + rule matcher + materiality screen, (3) alert
deduplication identity + append-only lifecycle events, (4) research invalidation + targeted
research launch stub (reuses Phase 3 plan validation; no LangGraph), (5) comparison matrix /
timeline builders from observation subjects, (6) PostgreSQL persistence (migration `0011`),
(7) loopback monitoring APIs. Semantic triage stays fail-closed
(`blocked_semantic_triage`). Native Swift timeline/matrix UI remains deferred (`ponytail:`
contracts + loopback first; UI later).

**Tech Stack:** Python 3.11+, Pydantic strict contracts, Psycopg 3, PostgreSQL 17, existing
pytest + real test DB. **No new third-party dependency.** Decimal for thresholds. No LLM triage.

## Global Constraints

1. Deterministic detection and materiality run **before** any semantic triage path.
2. Semantic triage is fail-closed (`blocked_semantic_triage`) until calibrated models exist.
3. Alert deduplication uses subject + rule + underlying event identity + time window + state
   transition; duplicates do not create a second open alert.
4. Alert lifecycle transitions are append-only immutable events.
5. Every alert and comparison cell navigates to raw envelope / observation evidence IDs.
6. Research invalidation records when observations are orphaned or quarantined; they reference
   report/assertion IDs when present.
7. Targeted research launch validates a Phase 3 retrieval plan shape and records a launch stub;
   it does **not** run LangGraph or claim monitoring-driven research complete (criterion 45 stays
   development-partial).
8. Comparison matrix / timeline are contract + loopback only; native UI criteria 4–8 remain open.
9. No live collectors, trading, exchange access, or new analytics backends.
10. Acceptance-matrix rows get **development partial** evidence only; no false criterion closure.
11. Failures are typed and sanitized; raw payloads never enter HTTP error bodies.

## Development-slice acceptance (must prove)

1. Strict contracts reject invalid rules, detections, materiality decisions, alerts, events,
   invalidations, launch stubs, comparison matrices, and timeline events.
2. Deterministic detectors emit measurements for threshold / rate-of-change / finality /
   quality transitions without invoking triage.
3. Rule matcher selects only development rule types; blocked rule types fail closed.
4. Materiality screen yields `record_only` … `critical` / `requires_more_evidence` from
   magnitude + confidence + thresholds (deterministic).
5. Alert dedup identity collapses duplicate detections inside the window into one alert.
6. Alert lifecycle progresses via append-only events; illegal transitions raise typed errors.
7. Orphaned/quarantined observation input produces a research invalidation record linking
   affected report IDs when supplied.
8. Targeted research launch stub validates plan shape and returns a launch record without
   executing a graph.
9. Comparison matrix and cross-chain timeline include subject, observation IDs, and envelope IDs.
10. Loopback APIs expose evaluate / alert lifecycle / invalidate / comparison / timeline without
    claiming native UI or live monitors.
11. Semantic triage endpoint/path fails closed with `blocked_semantic_triage`.

## Explicitly out of scope (blocked / later)

- Live collectors / WebSockets / Bitcoin Core RPC
- Calibrated semantic triage LLMs
- LangGraph durable monitoring-driven research graphs (criterion 45 full close)
- Native timeline / comparison matrix Swift UI (criteria 4–8)
- Full detector roster (rolling anomaly, structural break, document/schema/contract diffs, …)
- Criteria 45, 61, 82–84 closed as release evidence
- Phase 6 eval center, signing, backup, Safe Mode

---

## File structure

- `packages/contracts/src/rsi_atlas_contracts/monitoring.py` — rules, detections, materiality,
  alerts, invalidation, comparison/timeline
- `packages/contracts/tests/test_monitoring.py`
- `packages/monitoring/` — detectors, materiality, alerts, invalidation, comparison, triage stub
- `migrations/0011_monitoring_alerts.sql`
- `packages/storage/.../monitoring_repository.py`
- `services/engine/...` — loopback monitoring APIs
- README / production-plan / roadmap / acceptance-matrix — honest partial evidence only
- Replace stub: delete `2026-07-19-phase-5-monitoring-comparison-stub.md` after this plan lands

---

### Task 1: Strict monitoring + comparison contracts

**Files:**

- Create: `packages/contracts/src/rsi_atlas_contracts/monitoring.py`
- Modify: `packages/contracts/src/rsi_atlas_contracts/__init__.py`
- Create: `packages/contracts/tests/test_monitoring.py`

**Interfaces (minimum):**

- `MonitoringRuleType` + `DEVELOPMENT_RULE_TYPES` + `BLOCKED_RULE_TYPES`
- `MonitoringRule` (rule_id, type, subject_id, thresholds/params, severity floor)
- `ChangeKind`, `DeterministicMeasurement`, `ChangeDetection`
- `MaterialityOutcome`, `MaterialityDecision`
- `AlertLifecycle`, `Alert`, `AlertEvent`, `alert_id`, `alert_dedup_key`
- `InvalidationReason`, `ResearchInvalidation`
- `TargetedResearchLaunch` (launch_id, plan_hash, status=`recorded_stub`)
- `ComparisonAxis`, `ComparisonCell`, `ComparisonMatrix`
- `TimelineEventKind`, `TimelineEvent`, `CrossChainTimeline`
- `SemanticTriageRequest` / gate → always blocked in development

- [x] **Step 1: Write RED contract tests**
- [x] **Step 2: Run RED**
- [x] **Step 3: Implement smallest strict models**
- [x] **Step 4: Verify and commit**

```bash
uv run pytest packages/contracts/tests/test_monitoring.py -q
uv run ruff check packages/contracts && uv run ruff format --check packages/contracts
uv run mypy packages/contracts/src
git commit -m "feat: define monitoring and comparison contracts"
```

---

### Task 2: Detectors, rule matcher, materiality screen

**Files:**

- Create: `packages/monitoring/` workspace package
- Create: `packages/monitoring/src/rsi_atlas_monitoring/{detect,rules,materiality,triage}.py`
- Create: `packages/monitoring/tests/test_detect.py`, `test_rules.py`, `test_materiality.py`,
  `test_triage.py`
- Modify: root `pyproject.toml` workspace members + engine deps

- [x] **Step 1: RED** — previous/current pair detects delta; blocked rule type fails; triage blocked
- [x] **Step 2: Implement deterministic detectors + matcher + screen**
- [x] **Step 3: GREEN + commit**

```bash
uv run pytest packages/monitoring/tests -q
git commit -m "feat: add deterministic change detection and materiality screen"
```

---

### Task 3: Alert dedup, lifecycle, research invalidation

**Files:**

- Create: `packages/monitoring/src/rsi_atlas_monitoring/{alerts,invalidation,launch}.py`
- Create: `packages/monitoring/tests/test_alerts.py`, `test_invalidation.py`, `test_launch.py`

- [x] **Step 1: RED** — dedup collapses duplicates; lifecycle append-only; orphan invalidates;
      launch stub validates plan hash
- [x] **Step 2: Implement**
- [x] **Step 3: GREEN + commit**

```bash
uv run pytest packages/monitoring/tests/test_alerts.py packages/monitoring/tests/test_invalidation.py packages/monitoring/tests/test_launch.py -q
git commit -m "feat: add alert dedup, lifecycle, and research invalidation"
```

---

### Task 4: Comparison matrix + timeline builders

**Files:**

- Create: `packages/monitoring/src/rsi_atlas_monitoring/comparison.py`
- Create: `packages/monitoring/tests/test_comparison.py`

- [x] **Step 1: RED** — matrix cells and timeline events carry observation + envelope IDs
- [x] **Step 2: Implement builders**
- [x] **Step 3: GREEN + commit**

```bash
uv run pytest packages/monitoring/tests/test_comparison.py -q
git commit -m "feat: build comparison matrix and cross-chain timeline payloads"
```

---

### Task 5: Persistence (migration 0011) + repository

**Files:**

- Create: `migrations/0011_monitoring_alerts.sql`
- Create: `packages/storage/src/rsi_atlas_storage/monitoring_repository.py`
- Create: `packages/storage/tests/test_monitoring_repository.py`
- Modify: `packages/storage/src/rsi_atlas_storage/__init__.py`

- [x] **Step 1: RED** — persist alert + event + invalidation; dedup lookup returns existing
- [x] **Step 2: Migration + repository**
- [x] **Step 3: GREEN + commit**

```bash
uv run pytest packages/storage/tests/test_monitoring_repository.py -q
git commit -m "feat: persist monitoring alerts and research invalidations"
```

---

### Task 6: Loopback monitoring APIs

**Files:**

- Create: `services/engine/src/rsi_atlas_engine/monitoring.py`
- Modify: `services/engine/src/rsi_atlas_engine/api.py`, `runtime.py` (or wiring)
- Create: `services/engine/tests/test_monitoring_api.py`
- Modify: `services/engine/pyproject.toml` (+ monitoring package)

- [x] **Step 1: RED** — evaluate change → alert; lifecycle; invalidate; comparison; triage 422/503
- [x] **Step 2: Wire service**
- [x] **Step 3: GREEN + commit**

```bash
uv run pytest services/engine/tests/test_monitoring_api.py -q
git commit -m "feat: expose monitoring and comparison loopback APIs"
```

---

### Task 7: Honest docs + Phase 5 slice close

**Files:**

- Modify: `README.md`, `docs/production-plan.md`, `docs/acceptance-matrix.md`,
  `docs/superpowers/plans/2026-07-18-full-product-delivery-roadmap.md`, this plan (checkboxes)
- Delete: `docs/superpowers/plans/2026-07-19-phase-5-monitoring-comparison-stub.md`

- [x] **Step 1: Update evidence language (development partial only)**
- [x] **Step 2: Full focused verification**
- [x] **Step 3: Commit close**

```bash
uv run pytest packages/contracts/tests/test_monitoring.py packages/monitoring/tests packages/storage/tests/test_monitoring_repository.py services/engine/tests/test_monitoring_api.py -q
uv run ruff check packages/contracts packages/monitoring packages/storage services/engine
uv run mypy packages/contracts/src packages/monitoring/src
git commit -m "docs: close Phase 5 monitoring comparison development slice"
```

---

## Self-review

1. **Spec coverage (§24 + comparison UX):** change detection, rule match, materiality, alert
   lifecycle/dedup, dependency invalidation, targeted research stub, comparison/timeline — each
   has a task. Semantic triage and native UI remain explicit stubs/deferred.
2. **No placeholders:** tasks name files, interfaces, and commands.
3. **Type consistency:** `observation_id` / `envelope_id` / `subject_id` / `report_id` shared
   across detection → alert → invalidation → comparison/timeline.
4. **Honest closure:** criteria 45/61/82–84 stay open with development-partial evidence only.
