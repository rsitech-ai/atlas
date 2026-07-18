# RSI Atlas — Product and System Design Specification

**Status:** Approved design, awaiting written-spec review
**Date:** 2026-07-18
**Parent brand:** Research Signal Intelligence
**Product:** RSI Atlas
**Tagline:** *A local-first crypto intelligence and research operating system.*
**Canonical repository:** `rsi-atlas`
**Canonical Python package:** `rsi_atlas`
**Canonical Swift application:** `RSIAtlas`
**Canonical CLI:** `atlas`
**Primary platform:** Apple Silicon macOS, 24–36 GB unified memory
**Primary users:** Individual quantitative crypto researcher; small crypto hedge-fund research team
**Default privacy posture:** Strict zero egress for private data, prompts, model inputs, embeddings, traces, reports, and evaluations

---

## 1. Executive summary

RSI Atlas is a native macOS research workstation that transforms fragmented crypto documents, blockchain state, market data, governance activity, protocol metrics, and software-development activity into reproducible, evidence-backed research.

It is deliberately not a generic “chat with PDF” application. The durable product asset is a versioned evidence and research graph in which every material conclusion can be traced to an immutable document region, pinned chain observation, market-data partition, deterministic calculation, model execution, and analyst decision.

The system has two first-class experiences:

1. **RSI Atlas Workstation** — a professional analyst environment for protocol due diligence, cross-protocol comparison, continuous monitoring, quantitative exploration, evidence inspection, and citation-aware report editing.
2. **RSI Atlas Studio** — a developer and research-engineering environment for LangGraph traces, agent execution, parser and chunking experiments, retrieval comparisons, model and prompt evaluation, data-quality analysis, resource profiling, and controlled Codex-assisted engineering.

The architecture is a **modular monolith with isolated workers**:

- SwiftUI owns the native user experience, system lifecycle, Foundation Models integration, file access, Keychain, notifications, charts, and local service control.
- Python owns document intelligence, LangChain adapters, LangGraph orchestration, Pydantic contracts, retrieval, structured-data collection, deterministic analytics, evaluation, and report generation.
- Expensive or risky work runs in isolated processes: PDF/OCR, embeddings, reranking, local reasoning, vision, collection, feature computation, evaluation, and Codex.
- PostgreSQL plus pgvector is the operational source of truth; Parquet plus DuckDB provides historical analytics; a content-addressed local artifact store retains raw evidence and derived artifacts.
- Bitcoin uses a local Bitcoin Core node where practical. EVM and Solana use allowlisted read-only RPC/indexer providers with immutable local snapshots and provider-disagreement checks.
- Apple Foundation Models handles lightweight on-device semantic work. Larger local models run through a capability-routed MLX/Ollama-compatible model plane. Codex is an engineering agent, not the production research orchestrator.
- OpenTelemetry is the common local tracing standard. LangSmith concepts and compatible attributes are supported, but hosted LangSmith is disabled under strict zero-egress mode and self-hosted LangSmith is not required on the reference workstation.

RSI Atlas produces:

- cited protocol dossiers and investment-committee memos;
- tokenomics, security, governance, treasury, development, and market-risk analyses;
- cross-protocol and cross-ecosystem comparisons;
- material-change alerts;
- quantitative feature exports and backtest-ready point-in-time datasets;
- machine-readable evidence packages;
- complete reproducibility manifests.

RSI Atlas does **not** place trades, hold private keys, sign transactions, manage exchange accounts, or act as an autonomous investment decision-maker.

---

## 2. Product goals

### 2.1 Primary goals

RSI Atlas shall:

1. Ingest PDFs, HTML, protocol documentation, governance material, audit reports, GitHub activity, market feeds, protocol APIs, and blockchain observations.
2. Support Bitcoin, EVM ecosystems, and Solana in the first complete release.
3. Run fully locally on a 24–36 GB Apple Silicon workstation.
4. Support both a strictly offline profile and a controlled monitored-research profile.
5. Preserve raw evidence immutably and version every derived artifact.
6. Separate publisher claims, deterministic facts, model inferences, and analyst decisions.
7. Produce citation-ready evidence packets before synthesis.
8. Use deterministic code for validation, arithmetic, policy, state, and source-of-truth writes.
9. Use agents only where semantic judgment is necessary.
10. Make every workflow replayable, inspectable, interruptible, and recoverable.
11. Evaluate parser, chunker, retriever, reranker, prompt, model, judge, and graph changes against versioned local benchmarks.
12. Provide a polished native analyst workstation and an equally serious engineering laboratory.
13. Demonstrate production engineering: security boundaries, zero-egress verification, observability, CI gates, signed packaging, backup, restore, and failure recovery.
14. Permit an individual researcher to operate the complete system while retaining architecture suitable for a small research team.

### 2.2 Portfolio goals

The repository shall visibly demonstrate competence in:

- LangChain integration boundaries;
- LangGraph durable and multi-agent workflows;
- LangSmith-compatible evaluation and trace concepts;
- local LLM routing and Apple Foundation Models;
- Pydantic-based contracts and validation;
- multimodal PDF ingestion and chunking research;
- hybrid retrieval and reranking;
- evidence graphs, bitemporal data, and point-in-time correctness;
- multi-chain and market-data engineering;
- local-native macOS product development;
- security, packaging, testing, observability, and release operations;
- controlled AI-assisted software engineering with Codex.

### 2.3 Success definition

The first complete production-quality release succeeds when an analyst can:

1. Import or collect a protocol’s documents and structured evidence.
2. Observe parsing, fallback, chunking, indexing, extraction, and publication.
3. Ask a material research question.
4. Inspect the typed retrieval plan and every evidence candidate.
5. Run bounded specialist research across documents, chain state, market data, governance, and GitHub.
6. Review deterministic calculations and source conflicts.
7. Generate and edit a cited report.
8. Trace every material statement to exact evidence.
9. replay the workflow against a frozen snapshot;
10. detect a later material change and see which claims and reports became stale;
11. compare a candidate model, prompt, parser, chunker, or retriever against the production baseline;
12. diagnose a failure locally and create a sanitized Codex engineering task;
13. recover from a killed worker, corrupt derived index, or failed update without losing raw evidence or analyst decisions.

---

## 3. Non-goals

The initial product shall not:

- place trades or generate executable trading orders;
- access wallet private keys or blockchain signing keys;
- hold, transfer, stake, or custody assets;
- request exchange trading or account permissions;
- run full archival nodes for every supported chain on the reference Mac;
- globally archive every exchange tick, EVM trace, or Solana account;
- make model self-confidence the authoritative confidence score;
- treat embeddings or vector search as the source of truth;
- treat extracted publisher claims as independently verified facts;
- silently use remote models or hosted telemetry;
- require Kubernetes, Kafka, Elasticsearch, a dedicated graph database, or self-hosted LangSmith on the reference workstation;
- expose arbitrary SQL, shell, network, filesystem, or database tools to production agents;
- preserve hidden chain-of-thought as a product requirement;
- auto-merge, auto-push, or auto-deploy Codex-generated changes;
- claim that a generated report is investment advice or ground truth.

---

## 4. Users and operating model

### 4.1 Primary persona: individual quantitative crypto researcher

The solo profile requires:

- one-command local setup;
- sensible defaults;
- local notebook, CLI, and API access;
- low-memory modes;
- explicit resource controls;
- transparent calculations;
- reproducible experiments;
- research and engineering workflows on one workstation.

### 4.2 Secondary persona: small hedge-fund research team

The team-ready architecture requires:

- workspaces and projects;
- roles and permissions;
- analyst, reviewer, and publisher actions;
- immutable approval events;
- shared prompt, model, and source policies;
- audit history;
- report versions;
- review queues;
- portable research bundles.

The first release may expose a compact role model, but tenant, workspace, and actor identifiers are mandatory in all durable commands, records, and traces.

### 4.3 Roles

Initial roles are:

- `owner` — manages workspace, policies, models, and releases;
- `analyst` — imports evidence, runs research, edits drafts, and creates monitoring rules;
- `reviewer` — reviews claims, conflicts, evaluations, and report changes;
- `publisher` — approves final research artifacts;
- `engineer` — accesses Studio, experiments, traces, and Codex workflows;
- `system` — performs deterministic background operations under narrowly scoped capabilities.

One person may hold all roles in the solo profile. Role separation remains explicit in the data model.

---

## 5. Design principles

### 5.1 Evidence before conclusions

Every material conclusion shall be supported by exact evidence or deterministic calculations. Unsupported or unverifiable portions shall be visible.

### 5.2 Deterministic core, agentic edge

Hashing, validation, persistence, arithmetic, permissions, state transitions, indexing, and source-of-truth writes are deterministic. Agents classify, interpret, reconcile, plan, and draft within bounded schemas and policies.

### 5.3 Immutable inputs, versioned derivations

Raw artifacts never mutate. New parsers, chunkers, models, prompts, schemas, calculations, or normalizers produce new versions rather than overwriting historical state.

### 5.4 Point-in-time correctness

Historical research and backtests may use only information available at the requested as-of time. `available_time`, not merely `event_time`, controls eligibility.

### 5.5 Native semantics over false uniformity

Bitcoin UTXOs, EVM logs, Solana accounts, market events, and documents share provenance and time envelopes but retain source-specific payloads and rules.

### 5.6 Bounded autonomy

Every agent has one responsibility, typed inputs and outputs, restricted tools, a deadline, retry limits, evaluation fixtures, and no publication authority.

### 5.7 Honest degradation

Missing models, stale data, source disagreement, failed reranking, or insufficient evidence produce explicit degraded states or abstention, never fabricated completeness.

### 5.8 Inspectability by construction

The analyst can navigate from prose to assertion, claim, evidence link, source location, parser/collector/model run, and immutable artifact. The engineer can navigate the reverse direction.

### 5.9 Local-first resource discipline

One heavy model normally runs at a time. Backfills, OCR, evaluation, and Codex yield to active research and UI responsiveness.

### 5.10 Security as architecture

Zero-egress, process isolation, source quarantine, signed artifacts, Keychain credentials, and capability-based IPC are system properties verified by tests.

### 5.11 Benchmark sophistication, not novelty

A more complex chunker, agent, or judge is promoted only when it measurably improves the relevant benchmark without violating latency, memory, or safety gates.

---

## 6. Key architectural decisions

| Decision | Selected approach | Rationale |
|---|---|---|
| Product form | Native SwiftUI workstation | Best macOS UX, Apple Foundation Models access, Keychain, notifications, charts, file handling, and packaging story |
| Backend structure | Modular monolith with isolated workers | Strong boundaries and recovery without local microservice sprawl |
| Workflow orchestration | LangGraph custom workflows and subgraphs | Durable state, explicit routing, interrupts, retries, parallel specialists, and replay |
| Integration library | LangChain at adapter boundaries | Standard loaders, models, embeddings, retrievers, tools, and structured output without making LangChain the domain model |
| Contracts | Strict Pydantic schemas; generated Swift `Codable` models | Versioned, testable cross-process interfaces |
| Operational database | PostgreSQL plus pgvector | Consolidates state, evidence, relations, checkpoints, lexical search baseline, and vectors |
| Historical analytics | Parquet plus DuckDB | Efficient local columnar analytics without a distributed stack |
| Artifact storage | Content-addressed local filesystem abstraction | Immutable raw sources, parser artifacts, reports, models, and bundles |
| Blockchain access | Local Bitcoin Core; allowlisted EVM/Solana providers with local snapshots | Practical on reference hardware while preserving reproducibility |
| Retrieval | Dense + lexical + exact + structured + graph + time-series | No single retrieval method can answer all crypto research queries |
| Production chunking | Structure-aware hierarchical parent-child with table-specific representations | High recall, recoverable context, and exact source lineage |
| Model platform | Apple Foundation Models + capability-routed MLX/Ollama providers | Small local semantic tasks plus larger local reasoning without one-runtime lock-in |
| Evaluation | Local code evaluators, human labels, LLM judges, pairwise experiments | Production-grade regression gates under zero egress |
| Observability | OpenTelemetry to local stores; LangSmith-compatible concepts | Local inspectability with optional future exporter |
| Codex | Isolated engineering-plane agent | Useful for tests and patches without contaminating live research authority |
| Privacy profiles | Offline base + separately controlled monitored-research capability | Stronger than a runtime checkbox and compatible with continuous public-source collection |
| Packaging | Signed, notarized native app with embedded isolated runtime and signed helpers | Reproducible installation without system Python or cloud infrastructure |
| Release model | Human-approved, evaluation-gated, signed updates with rollback | Prevents silent behavioral changes in models, prompts, data, or code |

---

## 7. Product surface and visual design

### 7.1 Product modules

Canonical names are:

```text
RSI Atlas Workstation   Native analyst application
RSI Atlas Studio        Engineering, traces, agents, and evaluation workspace
RSI Atlas Engine        Python/LangGraph intelligence backend
RSI Atlas Monitor       Controlled collectors and material-change workflows
RSI Atlas Evidence      Claims, provenance, citations, and evidence lineage
RSI Atlas Research API  Local programmatic interface
```

### 7.2 Analyst Workstation navigation

```text
Command Center
Protocols & Assets
Research
Compare
Monitoring
Evidence
Data Explorer
Reports
System
```

The Workstation shall support:

- customizable dashboard layouts;
- dense tables with sorting, filtering, grouping, pinning, and export;
- synchronized market, on-chain, governance, development, and document charts;
- protocol and asset timelines;
- PDF rendering with highlighted evidence regions;
- citation-aware report editing;
- analyst notes and review decisions;
- cross-protocol comparison matrices;
- multi-window workflows;
- drag-and-drop imports;
- keyboard-first navigation and command palette;
- light and dark appearance;
- full accessibility and Reduce Motion support.

### 7.3 Engineering Studio navigation

```text
LangGraph Studio
Run & Trace Explorer
Agent Inspector
Parser Laboratory
Chunking Laboratory
Retrieval Laboratory
Data & Feature Laboratory
Prompt Registry
Model Registry
Evaluation Center
Connector Health
Codex Console
Runtime Console
```

### 7.4 Signature experiences

#### Research canvas

A three-pane research environment shall show:

- plan and graph execution;
- findings and editable analysis;
- exact evidence and lineage.

#### Evidence constellation

Claims connect visually to PDF regions, tables, chain observations, calculations, governance events, code changes, and analyst notes. The graph is functional: selecting an edge opens the exact relationship and source.

#### Cross-chain timeline

One UTC-aligned timeline shall display Bitcoin heights, EVM blocks, Solana slots, market events, governance actions, document versions, GitHub releases, incidents, and analyst annotations while retaining native event identity.

#### Trace replay

The user can scrub through a LangGraph execution, inspect state diffs, see retrieval candidates enter context, observe retries, and open node-specific model, prompt, validation, latency, and memory details.

### 7.5 Visual language

The visual language is hybrid:

- native, restrained, dense, and professional for ordinary work;
- selectively futuristic for live workflows, evidence graphs, model routing, and trace replay.

The base palette is neutral graphite with high-contrast text. Semantic accents encode state:

- blue — deterministic data and computation;
- violet — model or agent activity;
- cyan — active workflow execution;
- green — validated or healthy;
- amber — degraded, uncertain, or review required;
- red — conflict, critical risk, or failure.

Motion shall communicate causality, progression, or state. Decorative ambient animation is prohibited in information-dense surfaces.

### 7.6 Visibility presets

- **Analyst:** product and research features only;
- **Advanced:** analyst features plus selected execution details;
- **Engineering:** complete pipeline, model, trace, data, and evaluation visibility.

---

## 8. System context

RSI Atlas is a local desktop product whose trusted core runs on one Apple Silicon workstation. It may read public external sources only through the monitored collector boundary; no hosted model, vector database, telemetry service, or control plane is required.

```text
Analyst / Research Engineer
            ↓
RSI Atlas Workstation and Studio (SwiftUI)
            ↓ authenticated local IPC
RSI Atlas Engine and durable LangGraph workflows (Python)
            ↓
Isolated parser, model, retrieval, collector, evaluation, and Codex workers
            ↓
PostgreSQL/pgvector · Parquet/DuckDB · content-addressed artifacts
            ↓
Local Bitcoin Core and, only in monitored mode, allowlisted public sources
```

### 8.1 Trust boundary summary

- The native application is the human interaction and local lifecycle boundary.
- The Python engine is the research control plane and sole authority for application commands, publication, and durable state transitions.
- Untrusted documents, remote payloads, models, and engineering agents execute behind narrower process capabilities.
- External sources never write directly to production evidence stores; they produce quarantined immutable artifacts.
- Every published output is derived from a frozen local snapshot.

### 8.2 External dependencies

The offline profile depends only on macOS services, local storage, packaged runtimes, imported bundles, and an optional local Bitcoin Core node. The monitored profile additionally depends on explicitly allowlisted read-only websites, RPC/indexer endpoints, market-data providers, GitHub, governance sources, and the signed update feed.

Detailed component boundaries, IPC, runtime modes, hardware policy, and deployment profiles are normative in Sections 9 and 10.


## 9. System architecture

### 9.1 Selected pattern

RSI Atlas uses a **modular monolith with isolated workers**.

A single versioned Python codebase owns the domain model and application services. Resource-intensive or risky work runs in separate processes. This preserves clear boundaries, fault isolation, and independent resource control without introducing workstation-scale microservice overhead.

Rejected alternatives:

- A single Python process would make parser, OCR, model, and collector failures too destructive.
- Full local microservices would add ports, deployment manifests, schemas, and memory overhead without providing proportional value.

### 9.2 Top-level topology

```text
┌──────────────────────────────────────────────────────────────┐
│                    RSI Atlas Workstation                     │
│                         SwiftUI                              │
│                                                              │
│ Analyst Workstation · Engineering Studio · System Control   │
└───────────────────────────┬──────────────────────────────────┘
                            │
              XPC control + Unix-domain data sockets
                            │
┌───────────────────────────▼──────────────────────────────────┐
│                       RSI Atlas Engine                       │
│                                                              │
│ Local API · Command Bus · Event Stream · Scheduler          │
│ Auth/RBAC · Artifact API · Search API · Workflow API        │
└───────────────┬──────────────────┬───────────────────────────┘
                │                  │
       ┌────────▼────────┐ ┌───────▼─────────────────┐
       │ LangGraph       │ │ Deterministic services │
       │ orchestration   │ │                         │
       │ ingestion       │ │ validation             │
       │ research        │ │ calculations           │
       │ monitoring      │ │ normalization          │
       │ evaluation      │ │ feature engineering    │
       └────────┬────────┘ └────────┬────────────────┘
                │                   │
┌───────────────▼───────────────────▼──────────────────────────┐
│                    Isolated worker plane                     │
│                                                              │
│ PDF/OCR · Model · Embedding · Reranker · Vision             │
│ Collectors · Chain adapters · Evaluation · Export           │
└───────────────┬──────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────┐
│                        Local data plane                       │
│                                                              │
│ PostgreSQL + pgvector · Parquet + DuckDB · Artifact store   │
└──────────────────────────────────────────────────────────────┘
```

### 9.3 Swift responsibilities

Swift owns distinctly native concerns:

- Application lifecycle.
- Windows, scenes, navigation, commands, menus, keyboard shortcuts, and accessibility.
- File import and drag-and-drop.
- PDF rendering and visual overlays.
- Swift Charts and interactive visualizations.
- Keychain access.
- Notifications and menu-bar state.
- Backend service control.
- Apple Foundation Models execution through a restricted provider service.
- Native resource and health monitoring.

Swift does not implement retrieval, parsing, chain normalization, quantitative calculation, or research logic.

### 9.4 Python responsibilities

Python owns:

- FastAPI-compatible local service contracts.
- LangChain adapters and retrieval abstractions.
- LangGraph workflows.
- Pydantic schemas.
- Document parsing, OCR orchestration, chunking, embedding, reranking, and indexing.
- Research planning and bounded specialist agents.
- Chain, market, governance, protocol, and GitHub collectors.
- Entity resolution.
- Deterministic calculations and feature engineering.
- Evaluation, report generation, and publication.
- PostgreSQL, pgvector, DuckDB, Parquet, and artifact persistence.

### 9.5 Command, event, and query model

Commands request work:

```text
ImportDocument
StartInvestigation
CompareSubjects
GenerateDossier
RunEvaluation
ReplayWorkflow
CreateMonitoringRule
SynchronizeSource
ApproveClaim
PublishReport
```

Events describe state transitions:

```text
InvestigationStarted
ParserFallbackActivated
EvidenceConflictDetected
CitationValidationFailed
DocumentPublished
FeatureRecomputed
AlertPublished
InvestigationCompleted
```

Queries return current state:

```text
GetInvestigationState
GetEvidenceLineage
GetCollectorHealth
GetModelAvailability
GetReportVersion
```

All cross-process messages use versioned schemas. Swift `Codable` models are generated or contract-tested against the canonical schemas.

### 9.6 Worker roles

Logical roles include:

```text
atlas-api
atlas-worker-document
atlas-worker-model
atlas-worker-data
atlas-worker-evaluation
atlas-collector
atlas-exporter
```

They are not all permanently resident. The supervisor starts resource-heavy roles on demand.

Typical memory-aware flow:

```text
PDF imported
→ parser/OCR worker loads
→ canonicalization completes
→ parser worker exits
→ embedding worker loads
→ indexing completes
→ reasoning model loads for extraction
→ reasoning model unloads
```

### 9.7 IPC

Development mode may use HTTP over `127.0.0.1`.

Release mode uses:

- XPC for sensitive lifecycle and capability issuance.
- Unix-domain sockets for typed data-plane requests and streaming events.
- Owner-only socket permissions.
- Peer identity verification.
- Short-lived capability tokens.
- Message-size, deadline, actor, workspace, schema, and trace validation.

No production listener binds to a LAN interface.

### 9.8 LangGraph boundary

LangGraph controls:

- Workflow state.
- Conditional routing.
- Specialist subgraphs.
- Checkpoints.
- Retries.
- Interrupts and resumption.
- Bounded repair loops.

Application services control:

- Persistence rules.
- Permissions.
- Network policy.
- Source-of-truth records.
- Deterministic calculations.
- Artifact lifecycle.
- Publication transactions.

UI code never invokes arbitrary graph nodes directly.

### 9.9 Runtime modes

```text
Research mode
├── application and database
├── ingestion and retrieval
├── research model
├── embeddings and reranker
└── critical monitoring

Engineering mode
├── source worktree
├── Codex
├── tests
├── evaluation runner
└── reduced research services

Evaluation mode
├── frozen datasets
├── candidate configurations
├── judges
└── minimal supporting services
```

Heavy research and Codex models are not resident simultaneously by default.

## 10. Deployment profiles and hardware policy

### 10.1 Offline profile

The offline profile performs no external network communication.

Permitted:

- Manual file import.
- Watched local folders.
- Signed research-data bundles.
- Signed model bundles.
- Signed application updates.
- Unix-domain sockets.
- Loopback access to an explicitly configured local Bitcoin node.

Prohibited:

- Remote model APIs.
- Remote embeddings.
- LangSmith SaaS.
- Analytics SDKs.
- Automatic update checks.
- Remote images or document resources.
- Arbitrary outbound HTTP.

### 10.2 Monitored-research profile

The monitored profile permits read-only external collection through a separately controlled collector boundary.

Permitted only through policy:

- Allowlisted protocol and governance sources.
- EVM and Solana RPC or indexer endpoints.
- Public market-data endpoints.
- GitHub read-only APIs.
- Signed application update feed.

No private document, prompt, embedding, trace, analyst note, model input, or generated report may leave the machine.

### 10.3 Hardware profiles

#### 24 GB

- Primary research model: approximately 7B–9B class, quantized, subject to benchmark.
- One heavy model at a time.
- Embedding and reranking loaded on demand.
- One OCR job at a time.
- One or two ingestion workers.
- Batch evaluations queued.

#### 32–36 GB

- Primary research model: approximately 12B–14B class, quantized, subject to benchmark.
- One heavy reasoning or vision model at a time.
- Embedding or reranker may remain resident when measured safe.
- Two or three ingestion workers where resource checks permit.
- Larger candidate judge or engineering model used sequentially.

Model class is not a contractual guarantee. Promotion depends on actual memory, context, latency, throughput, thermal, swap, and quality measurements on the reference hardware.

## 11. Domain and evidence model

### 11.1 Domain hierarchy

```text
Workspace
└── Research Project
    ├── Subjects
    ├── Investigations
    ├── Monitoring Rules
    ├── Reports
    ├── Evaluation Runs
    └── Analyst Decisions
```

### 11.2 Subject model

Supported subject types include:

```text
Protocol
Crypto Asset
Blockchain Network
Organization
Governance System
Smart Contract
Solana Program
Bitcoin Entity
Wallet or Treasury
Exchange
Repository
Market
```

Subjects connect through typed relationships such as:

```text
operates_on
issues
governed_by
developed_in
deployed_as
controlled_by
audited_in
competes_with
```

### 11.3 Canonical identity

Every canonical entity has:

```text
immutable internal ID
entity type
canonical name
aliases
external identifiers
chain-specific identifiers
validity period
resolution confidence
resolution evidence
```

Entity resolution creates an auditable decision:

```text
auto_resolved
analyst_confirmed
ambiguous
rejected
superseded
```

No alias merge is silent. Wrapped, bridged, deprecated, and unofficial assets remain distinguishable.

### 11.4 Source and artifact

A source describes a publisher or provider and its trust, access, and collection policies.

An artifact is immutable and content-addressed:

```text
artifact ID
content hash
source
original locator
retrieval and publication times
MIME type
size
storage location
acquisition method
collector version
signature/checksum
quarantine status
```

Artifact types include PDF, HTML, JSON, RPC payload, blockchain extract, market batch, repository archive, governance object, and analyst-imported data.

Changed content creates a new artifact version. Version relationships include:

```text
replaces
amends
duplicates
derived_from
translated_from
snapshot_of
```

### 11.5 Canonical document

A parsed PDF becomes a canonical document before chunking:

```text
Canonical Document
├── metadata
├── pages
├── sections
├── headings
├── paragraphs
├── lists
├── tables
├── figures
├── captions
├── footnotes
├── references
├── annotations
└── spatial coordinates
```

Each element stores page, reading order, bounding box, raw text, normalized text, parent section, parser confidence, OCR confidence, language, source hash, and parser-run identity.

### 11.6 Parser run

Every parser attempt is retained with:

```text
parser name and version
configuration
input artifact hash
start and finish time
outputs
warnings
quality metrics
resource use
status
```

Fallback never erases the original candidate.

### 11.7 Chunk model

A chunk is a retrieval projection, not source truth.

```text
Chunk
├── canonical document version
├── strategy and configuration
├── ordered source elements
├── embedding input text
├── optional generated contextual prefix
├── parent and neighbors
├── token count
├── metadata
└── quality measurements
```

Multiple chunk sets may coexist for one document. Embeddings are separate versioned records and do not mutate chunks.

### 11.8 Observation model

Structured external data becomes an immutable observation with:

```text
observation type
subject
source artifact
raw envelope
event time
available time
collection time
validity period
value or typed payload
unit and currency
chain/market context
quality
finality
normalization version
provenance
```

Observation families include chain, market, protocol, governance, and development records.

### 11.9 Bitemporal history

Relevant records carry:

- `valid_time`: when the fact or state applies.
- `system_time`: when RSI Atlas recorded that version.
- `available_time`: when the information could legitimately have been known.

This supports historical “as-of” research and prevents future-information leakage.

### 11.10 Claims

A claim is an atomic, reviewable proposition.

```text
Claim
├── subject
├── predicate
├── object or normalized value
├── natural-language statement
├── category
├── effective time
├── origin
├── model/prompt metadata
├── validation state
├── review state
└── evidence links
```

Origins:

```text
source_asserted
model_extracted
deterministically_computed
model_inferred
analyst_asserted
```

A source assertion means “the source claims this,” not “RSI Atlas verified this.”

### 11.11 Evidence links

Typed relationships connect claims and evidence:

```text
supports
contradicts
qualifies
provides_context
derived_from
supersedes
duplicates
cannot_verify
```

Each link records relevance, entailment, temporal compatibility, extraction confidence, validator result, and analyst decision.

### 11.12 Deterministic calculations

Calculations are first-class evidence:

```text
Calculation
├── type
├── formula
├── implementation version
├── input observations
├── parameters
├── output value
├── unit
├── execution environment
├── test status
└── reproducibility hash
```

Examples include dilution, supply projections, treasury runway, holder concentration, governance participation, volatility, funding basis, liquidity depth, protocol revenue, and development trends.

### 11.13 Research assertions

A higher-order assertion connects claims, calculations, assumptions, contradictions, materiality, confidence, and review state.

Statuses:

```text
draft
machine_validated
requires_review
analyst_approved
rejected
superseded
```

### 11.14 Confidence profile

Confidence is multidimensional rather than an LLM self-rating:

```text
source reliability
source independence
extraction quality
evidence coverage
entailment strength
contradiction severity
numerical validation
temporal freshness
entity-resolution certainty
model agreement
analyst review
```

An overall display score may exist, but all components remain inspectable.

### 11.15 Reports

Reports are versioned research artifacts containing sections, assertions, charts, tables, citations, edits, approvals, exports, and a reproducibility manifest.

A report manifest records:

```text
document versions
chain heights and hashes
market cut-off
collector versions
calculation versions
chunker and embedding versions
retriever and reranker versions
model and prompt versions
evaluation results
analyst approvals
generation time
```

### 11.16 Data invariants

1. Raw artifacts are immutable.
2. Every derived record identifies source inputs.
3. Every model output records model, prompt, schema, and execution versions.
4. Every calculation records implementation and parameters.
5. Every citation resolves to an exact source location or structured observation.
6. Chain conclusions are tied to pinned state.
7. Source claims are not silently treated as facts.
8. Conflicting evidence remains visible.
9. Published reports use frozen investigation snapshots.
10. Approval is an immutable event.
11. Deleting or invalidating evidence propagates to dependencies.
12. Reprocessing creates new versions rather than rewriting history.

### 11.17 Storage mapping

#### PostgreSQL + pgvector

- Workspaces, users, subjects, identities.
- Artifacts and versions.
- Canonical document metadata.
- Chunks and embeddings.
- Observations, claims, evidence links, calculations, assertions.
- Investigations, workflows, reports, approvals, evaluations, and audit events.

#### Artifact store

- Original files.
- HTML and RPC snapshots.
- Page images and OCR artifacts.
- Parser outputs and tables.
- Model artifacts.
- Reports, traces, and reproduction bundles.

#### Parquet + DuckDB

- Historical market data.
- Large chain extracts.
- Feature matrices.
- Backtesting data.
- Historical traces and evaluation exports.

A dedicated graph database is deferred until measured traversal workloads justify it.
## 12. Document ingestion and intelligence

### 12.1 Publication lifecycle

A document becomes searchable only after passing all relevant gates.

```text
DISCOVERED
→ QUARANTINED
→ ADMITTED
→ PREFLIGHTED
→ PARSING
→ PARSE_VALIDATED
→ CANONICALIZED
→ CHUNKED
→ INDEX_VALIDATED
→ INTELLIGENCE_EXTRACTED
→ PUBLISHED
```

Exceptional states remain explicit:

```text
DUPLICATE
SUPERSEDED
AWAITING_PASSWORD
AWAITING_REVIEW
DEGRADED
REJECTED
FAILED_RETRYABLE
FAILED_TERMINAL
ARCHIVED
```

Partially processed content never appears in production retrieval.

### 12.2 Entry points

```text
Manual
├── file picker
├── drag-and-drop
├── watched folder
├── CLI
├── local API
└── signed offline bundle

Monitored
├── allowlisted website
├── protocol documentation
├── governance
├── GitHub
├── audit firm
├── RSS/announcement
└── imported research export
```

All entry points emit the same `AcquisitionEnvelope` containing workspace, source policy, method, filename, locator, times, MIME information, size, content hash, collector version, network profile, and raw-artifact location.

### 12.3 Admission and quarantine

Before third-party parsing, deterministic checks include:

- File signature and MIME consistency.
- Size and page-count limits.
- Encryption and password state.
- Malformed PDF structures.
- Embedded files, JavaScript, actions, and suspicious references.
- Decompression ratio.
- Duplicate hash and known version.
- Source policy.
- Available disk.

Admission outcomes:

```text
accept
accept_with_restrictions
request_password
quarantine_for_review
reject_policy_violation
reject_unsafe
mark_exact_duplicate
register_new_version
```

Parser workers receive read-only access to one artifact, a separate staging directory, no network, no secrets, bounded resources, and a unique run identity.

### 12.4 Preflight profiling

A lightweight profiler records:

```text
page count
file size
text-extractability ratio
image-only page ratio
characters by page
font/encoding anomalies
probable language
multi-column likelihood
table and figure likelihood
mathematical notation likelihood
header/footer patterns
scan quality
document-family candidates
```

Document families include whitepaper, technical paper, tokenomics, audit, governance, legal or regulatory disclosure, treasury, market research, exchange report, on-chain analytics report, presentation, and unknown.

### 12.5 Parser portfolio

#### Tier 0: native fast extraction

Metadata, page geometry, text spans, fonts, links, and basic images for straightforward born-digital PDFs.

#### Tier 1: structure-aware parsing

The primary candidate is a local structure-aware parser capable of headings, tables, figures, layout, hierarchy, and spatial provenance. Docling is the initial implementation candidate, but promotion depends on the parser benchmark.

#### Tier 2: OCR and layout fallback

OCR may run on the entire document, selected pages, or selected regions. Alternative engines, higher-resolution rendering, deskew, denoise, and table-specific processing remain benchmarked options.

#### Tier 3: local vision-language repair

A local VLM receives only difficult page images or crops such as token-allocation diagrams, complex vesting tables, scanned audit findings, dense figures, and visually encoded governance structures.

#### Tier 4: analyst review

Review is required when parser candidates disagree materially, important tables cannot be reconstructed, reading order remains ambiguous, OCR is below policy, a document is encrypted, or a material document would otherwise publish in degraded form.

### 12.6 Ingestion graph

```text
START
→ register_acquisition
→ run_admission_policy
   ├── reject → record_rejection → END
   ├── duplicate → link_existing_version → END
   └── accept
→ run_preflight
→ create_parser_plan
→ run_parser_candidates
→ normalize_candidate_outputs
→ score_parser_candidates
   ├── fallback_required → rerun bounded candidate path
   ├── review_required → INTERRUPT
   └── accepted
→ build_canonical_document
→ validate_canonical_document
→ enrich_document
→ generate_chunk_sets
→ evaluate_chunk_sets
→ select_publication_chunk_policy
→ embed_and_build_indexes
→ extract_document_intelligence
→ validate_claims_and_numbers
→ run_publication_gate
   ├── review_required → INTERRUPT
   ├── reject → archive_run → END
   └── approve
→ atomically_publish_document_version
→ emit_downstream_events
→ END
```

Graph state stores identifiers and compact decisions, not large document payloads. Side-effecting nodes use idempotency keys, staging records, content hashes, and transactional outbox events.

### 12.7 Parser-quality validation

#### Completeness

- Pages represented.
- Non-empty page coverage.
- Expected versus extracted characters.
- Image-only pages lacking OCR.
- Missing tables, figures, headings, or final pages.
- Unresolved glyph and replacement-character rates.

#### Structure

- Heading hierarchy.
- Reading order.
- Column mixing.
- Paragraph fragmentation.
- Header/footer contamination.
- Table-cell coverage.
- Caption, footnote, and list association.

#### Content sanity

- Duplicate pages or blocks.
- Broken words and hyphenation.
- Numeric-token loss.
- Percentage, currency, address, token-symbol, code identifier, and function-name preservation.

#### Crypto-specific invariants

- EVM addresses preserved.
- Solana addresses preserved.
- Bitcoin addresses and transaction IDs preserved.
- Token allocations plausible.
- Vesting dates consistent.
- Audit finding identifiers present.
- Table row and column headers intact.

### 12.8 Semantic parser assessment

A constrained local judge may assess selected page images against parser candidates and return:

```text
probable omissions
reading-order assessment
table interpretation
heading/section assessment
semantic corruption
page regions
recommended action
confidence dimensions
cited visual evidence
```

Allowed actions are limited to selecting an alternative, merging specific elements, rerunning selected pages, applying OCR or VLM repair, or requesting human review. The judge cannot publish or directly rewrite the canonical document.

### 12.9 Canonicalization

Canonicalization performs:

- Stable element IDs.
- Reading-order normalization.
- Heading-tree construction.
- Header/footer detection.
- Paragraph reconstruction.
- Hyphenation repair.
- Unicode normalization.
- Coordinate normalization.
- Table and figure relationships.
- Footnote and reference links.
- Language and document-family tagging.

Raw and normalized text are both retained. Pydantic uses strict fields, discriminated unions, explicit coordinate systems, controlled enums, rejected unknown fields, and versioned migrations.

### 12.10 Enrichment

Independent annotations include:

```text
document and section taxonomy
language and jurisdiction
protocol and asset entities
chains and networks
organizations and people
contracts and wallets
tokenomics concepts
audit findings
governance mechanisms
treasury concepts
risk taxonomy
temporal expressions
summary hierarchy
```

Enrichment order:

1. Deterministic recognizers.
2. Local dictionaries and entity registries.
3. Apple Foundation Models for light tasks.
4. Larger local model for ambiguity.
5. Analyst review for material unresolved entities.

Annotations never mutate canonical text.

## 13. Chunking framework

### 13.1 Strategy contract

Each strategy produces a versioned `ChunkSet` containing strategy identity, configuration hash, canonical document version, chunks, relationships, quality metrics, embedding state, and evaluation status.

### 13.2 Supported strategy families

1. Whole-document or whole-section.
2. Fixed-character.
3. Fixed-token.
4. Recursive.
5. Sentence and paragraph.
6. Page-based.
7. Heading- and section-aware.
8. Layout-aware.
9. Sliding-window.
10. Semantic-breakpoint.
11. Parent-child.
12. Small-to-big dynamic expansion.
13. Proposition or atomic-claim.
14. Contextualized chunks.
15. Table-aware.
16. Figure- and caption-aware.
17. Summary and multi-representation indexing.
18. Late-chunking experiment.
19. Query-aware dynamic assembly.
20. Agentic segmentation experiment.

### 13.3 Production policy

The first production policy is:

> Structure-aware hierarchical chunking with parent-child retrieval, table-specific representations, and optional contextual prefixes.

Initial benchmark targets:

```text
child passage       approximately 250–450 tokens
parent section      approximately 900–1,800 tokens
overlap             structural where possible
table row           complete row + headers + caption
atomic claim        claim representation + source parent
```

Document-family policies:

```text
Whitepaper          heading-aware parent-child
Audit report        finding-aware, code-aware, parent-child
Tokenomics          section-aware, table-aware, proposition representations
Governance          whole proposal or section-aware
Legal disclosure    clause-aware with definition context
Market report       heading-aware with chart/table representations
```

### 13.4 Table representations

Each table may produce:

- Complete structured table.
- Row-level chunks with repeated headers.
- Column-oriented summaries.
- Deterministic cell facts.
- Generated natural-language description clearly marked as generated.

The original table remains authoritative.

### 13.5 Evaluation

Intrinsic metrics:

```text
token distribution
oversized/undersized rate
broken sentence rate
orphan heading/caption rate
table split rate
section-path completeness
duplicate and overlap ratios
source continuity
address/numeric preservation
```

Retrieval metrics:

```text
Recall@k
Precision@k
MRR
nDCG
evidence-span recall
table-cell recall
multi-hop coverage
duplicate-result rate
context token cost
latency
index size
```

Downstream metrics:

```text
answer correctness
claim faithfulness
citation correctness and completeness
numerical accuracy
contradiction detection
abstention quality
judge agreement
analyst preference
```

The normal ingestion path builds one production set and one recursive baseline. Experimental sets are created on demand.

## 14. Embedding and index publication

### 14.1 Build flow

```text
validated chunks
→ construct embedding inputs
→ content-hash cache lookup
→ adaptive local batching
→ generate embeddings
→ validate vectors
→ build staging dense index
→ build lexical index
→ build metadata and relationship indexes
```

Every embedding records model artifact, tokenizer, dimensions, normalization, source chunk hash, input policy, and hardware/runtime metadata.

Vector checks include expected dimensions, finite values, non-zero norm, duplicate anomalies, cardinality, and model-version consistency.

### 14.2 Initial indexes

- pgvector dense index.
- PostgreSQL lexical/full-text index.
- Exact identifier index.
- Relational metadata and evidence-edge indexes.
- Optional local Tantivy/BM25 adapter only after benchmark justification.

### 14.3 Atomic publication

```text
build staging records
→ verify counts and lineage
→ commit publication manifest
→ atomically activate document version
→ deactivate superseded retrieval version
→ emit DocumentPublished
```

The manifest includes admitted artifact, canonical version, parser runs, quality report, enrichment, chunk set, embeddings, lexical index, extraction versions, warnings, evaluations, and approvals.

### 14.4 Reprocessing

Changes propagate through dependency-aware invalidation:

```text
parser change      → canonical document, chunks, embeddings, claims, reports
chunker change     → chunks, embeddings, retrieval evaluations
embedding change   → embeddings and retrieval evaluations
prompt change      → extracted claims/assertions/reports
metadata correction→ only affected dependencies
```

Supported operations include dry-run impact analysis, canary reprocessing, comparison, promotion, rollback, and selected-page or selected-section rerun.

## 15. Structured document intelligence

Specialized extractors may produce:

```text
ProtocolIdentityExtraction
TokenomicsExtraction
VestingScheduleExtraction
AuditFindingExtraction
AdministrativeControlExtraction
GovernanceMechanismExtraction
TreasuryDisclosureExtraction
RiskDisclosureExtraction
RoadmapExtraction
PartnershipClaimExtraction
MarketClaimExtraction
```

Each extractor follows:

```text
retrieve relevant canonical regions
→ generate strict structured output
→ Pydantic validation
→ deterministic business rules
→ source-span verification
→ cross-section reconciliation
→ optional independent review
→ publish draft claims
```

LLM repair may correct schema-format defects. It may not bypass domain-rule failures.

## 16. Retrieval and context assembly

### 16.1 Retrieval lifecycle

```text
Analyst question
→ query normalization
→ entity and identifier resolution
→ temporal scope resolution
→ intent and evidence-requirement classification
→ typed retrieval plan
→ parallel candidate generation
→ normalization and fusion
→ local reranking
→ parent/evidence expansion
→ coverage, freshness, and contradiction checks
→ bounded repair
→ structured EvidencePacket
```

### 16.2 Query contract

A `ResearchQuery` includes workspace, project, text, subject IDs, as-of time, time range, chains, included/excluded sources, research mode, freshness policy, latency budget, and context budget.

The derived `QueryIntent` includes query family, resolved subjects, unresolved entities, temporal scope, comparison axes, evidence requirements, calculation requirements, data planes, answer shape, materiality, and ambiguity.

### 16.3 Query families

- Exact lookup.
- Narrative explanation.
- Numerical analysis.
- Temporal or trend analysis.
- Cross-protocol comparison.
- Contradiction or verification.
- Event investigation.
- Exploratory research.

Each family has a distinct retrieval and validation policy.

### 16.4 Entity resolution

Order:

```text
exact canonical identifier
→ workspace alias
→ chain-qualified lookup
→ time-qualified lookup
→ deterministic similarity
→ local semantic assessment
→ analyst review for material ambiguity
```

A material query cannot proceed on an unresolved subject.

### 16.5 Data cutoff

Every query freezes a `DataCutoffManifest` containing effective as-of time, document, market, GitHub, governance, and chain cutoffs, pinned chain snapshots, staleness findings, and a manifest hash.

“Current” means the most recent locally published and validated snapshot, not an invisible live provider call.

### 16.6 Typed plan

Each `RetrievalStep` declares:

```text
data plane
retriever
query
filters
top_k
dependencies
expected evidence
required/optional status
```

The planner may use a local model. A deterministic validator enforces allowed data planes, fan-out, query count, dates, subjects, tool permissions, and budgets.

### 16.7 Retrieval data planes

#### Dense document retrieval

Passages, parent sections, contextualized chunks, propositions, summaries, questions-answerable representations, figure descriptions, and table representations.

#### Lexical retrieval

Addresses, symbols, finding IDs, proposal numbers, clauses, dates, percentages, function names, repository identifiers, and rare terminology.

#### Structured relational retrieval

Subjects, claims, audit findings, document versions, allocations, vesting, governance, treasuries, trust policies, and review states.

#### Time-series retrieval

Market, chain, protocol, governance, and development series through DuckDB/Parquet and deterministic analytical services.

#### Evidence-edge traversal

Claim-to-evidence, assertion-to-calculation, document-version, subject-to-contract, and report-to-source traversal.

#### Chain-snapshot retrieval

Exact contract state, token supply, upgrade authority, program state, multisig state, UTXO state, and transaction or event history.

#### Development retrieval

Commits, releases, advisories, diffs, contributors, issues, and pull requests.

#### Calculation retrieval

Reuse an existing validated calculation when inputs, parameters, version, subject, and period match; otherwise emit a calculation request.

### 16.8 Common candidate contract

Every retriever returns an `EvidenceCandidate` containing evidence reference, subjects, source family, text or payload reference, times, method, raw score, rank, reliability profile, provenance, and index versions.

Structured evidence remains structured; it is not flattened into authoritative prose.

### 16.9 Hybrid candidate generation

Initial benchmark defaults:

```text
dense child candidates          40
lexical candidates              40
exact identifier candidates     all valid, policy capped
summary/proposition candidates  20
fused pool                      roughly 50–80
cross-encoder input             roughly 30–50
final evidence                  roughly 8–20
```

These are experiment parameters rather than permanent constants.

### 16.10 Query rewriting

Allowed transformations:

- Spelling and symbol normalization.
- Alias and acronym expansion.
- Chain and temporal qualification.
- Multiple bounded variants.
- Multi-hop decomposition.
- Experimental hypothetical-answer retrieval.

The original query remains attached. Rewrites may not silently change subject, dates, or numerical thresholds.

### 16.11 Fusion

The first production fusion method is intent-weighted reciprocal-rank fusion:

```text
RRF(candidate) = Σ weight(retriever) / (k + rank)
```

Fusion also performs canonical evidence deduplication, parent grouping, document-version preference, exact-match promotion, superseded-source demotion, temporal rejection, workspace filtering, and source-diversity accounting.

Relevance and reliability remain separate scores.

### 16.12 Reranking

```text
fused candidates
→ deterministic eligibility filters
→ local cross-encoder
→ evidence-aware feature adjustment
→ optional constrained LLM reranker
→ final candidates
```

Deterministic filters reject wrong subject, wrong network, invalid period, superseded version, insufficient finality, missing provenance, access violation, and duplicates.

The optional LLM reranker returns typed relevance, directness, temporal fit, evidence role, and exclusion reason. It cannot rewrite evidence.

### 16.13 Expansion

Context expands according to evidence type:

- Prose: heading path, defining predecessor, conditional successor, footnotes.
- Audit: title, severity, component, description, recommendation, response, remediation.
- Table: title, headers, row labels, units, footnotes, selected neighbors.
- Governance: title, action, parameters, result, execution, discussion.
- Chain: pinned state, decoded event/state, identity, normalization, transaction context.

Generated context is never displayed as source quotation.

### 16.14 Multi-hop retrieval

Complex investigations use bounded workers with explicit dependencies. Workers return candidates, structured results, calculation requests, missing requirements, and warnings. They do not produce final conclusions.

### 16.15 Coverage matrix

Every material question evaluates requirements as:

```text
satisfied
partially_satisfied
conflicted
stale
missing
not_applicable
```

Deterministic checks verify type, location, time, identity, fields, independent-source count, calculation inputs, contradictions, and freshness before semantic sufficiency judgment.

### 16.16 Sufficiency judge and repair

The judge returns supported and unsupported subquestions, weak evidence, unresolved contradictions, proposed repairs, and abstention reason.

Allowed repairs:

```text
rewrite query
add exact search
expand time range
search another representation
retrieve parent
search structured claims
request chain snapshot
run calculation
decompose subquestion
request analyst input
abstain
```

Initial limits:

- Maximum two planning-repair rounds.
- Maximum four query variants per subquestion.
- Policy-controlled worker count.

### 16.17 Contradiction-aware retrieval

Material questions automatically probe negations, alternative terms, later versions, chain verification, independent sources, and known risk patterns.

The final packet should contain strongest support, strongest contradiction, material qualification, and missing independent confirmation.

### 16.18 EvidencePacket

The reasoning workflow receives a structured packet containing query, intent, data cutoff, evidence groups, calculations, coverage matrix, unresolved conflicts, missing evidence, and context manifest.

Items are explicitly typed as:

```text
SOURCE_CONTENT
GENERATED_METADATA
DETERMINISTIC_CALCULATION
ANALYST_NOTE
MODEL_INFERENCE
```

### 16.19 Context budget

Default allocation starts near:

```text
35% direct primary evidence
20% structured observations and calculations
15% contradictory evidence
10% definitions and parent context
10% temporal/version context
10% provenance and limitations
```

Policies vary by query family. Comparative analysis allocates evidence fairly across subjects. Numerical analysis prioritizes inputs, formulas, assumptions, and units.

### 16.20 Retrieval security

Retrieved content is untrusted data.

- It never enters system instructions.
- Tool access remains narrow.
- Instruction-like source content is detected and logged.
- Model outputs use strict schemas.
- Filesystem, database, and network policy live outside the model.
- Adversarial documents are part of regression evaluation.

### 16.21 Replay

Retrieval records query and plan hashes, cutoff manifest, publication and index versions, model versions, fusion and reranker configuration, context policy, and code version.

Replay modes:

```text
Exact replay        stored candidates and packet
Recomputed replay   same versions against frozen data
Comparative replay  candidate retriever/reranker against frozen data
```

### 16.22 Graceful degradation

- No vector index: lexical, exact, structured, and graph retrieval continue; semantic coverage is degraded.
- No reranker: fused ranking continues with visible downgrade.
- No large model: deterministic coverage remains; material output requires review.
- Stale structured data: current quantitative conclusions are blocked.
- Missing chain snapshot: collect/import or abstain.
- One weak source: show result and missing independent verification.

## 17. Multi-agent research and synthesis

### 17.1 Coordination pattern

RSI Atlas uses:

- A custom LangGraph workflow as the outer architecture.
- A lightweight typed router for workflow selection.
- Orchestrator-worker fan-out for complex research.
- Handoffs only for explicit user-facing mode transitions.

It does not use a free-form supervisor with unrestricted tool authority.

### 17.2 Research graph

```text
START
→ validate_investigation_request
→ freeze_data_cutoff_manifest
→ resolve_subjects_and_scope
   ├── material ambiguity → INTERRUPT
   └── resolved
→ load_research_policy
→ construct_investigation_plan
→ validate_plan_and_budget
→ dispatch_specialist_workers
→ validate_specialist_findings
→ run_missing_evidence_analysis
   ├── repairable → bounded retrieval expansion
   ├── material gap → INTERRUPT or ABSTAIN
   └── sufficient
→ run_contradiction_investigation
→ execute_deterministic_calculations
→ construct_assertion_graph
→ synthesize_structured_report_draft
→ bind_citations
→ run_deterministic_validators
→ run_semantic_judges
   ├── targeted repair
   ├── analyst review
   ├── reject
   └── pass
→ freeze_investigation_snapshot
→ publish answer/report
→ END
```

Graph state contains IDs, versions, counters, compact decisions, and pending review. Full evidence, time series, model outputs, and report sections remain outside checkpoint state.

### 17.3 Investigation specification

Each run declares:

```text
investigation type
primary and comparison subjects
research question
investment horizon
historical as-of date
required evidence planes
mandatory analytical sections
scenario assumptions
materiality policy
freshness policy
source-independence requirements
execution budgets
output format
approval level
```

A protocol dossier normally covers:

```text
purpose and architecture
competitive position
token utility
value accrual
supply and dilution
vesting and unlocks
treasury and runway
governance and control
smart-contract and operational security
on-chain usage
market structure and liquidity
development activity
regulatory and dependency risks
bull/base/bear scenarios
unresolved questions
material risks
```

The planner may add tasks but cannot remove mandatory sections without a policy decision.

### 17.4 Specialist registry

#### Document Evidence Analyst

Locates primary document evidence, reconciles versions, extracts publisher claims, identifies conditions and amendments, and distinguishes promise from verified implementation.

#### Tokenomics Analyst

Reconstructs supply, issuance, burn, emissions, vesting, and governance powers; requests deterministic dilution calculations; compares documents to chain state.

#### Security Analyst

Reviews audits, scope, remediation, upgradeability, emergency controls, administrators, affected components, and chain-specific implementation risks.

#### Governance Analyst

Analyzes proposals, participation, delegation, multisigs, councils, vetoes, emergency powers, documented governance, and actual execution.

#### Treasury and Fundamentals Analyst

Identifies controlled treasuries, balances, operating-cost assumptions, fees, revenue, incentives, liabilities, and runway inputs.

#### On-chain Analyst

Interprets validated chain observations, supply, flows, holders, treasuries, usage, contracts, programs, and document-to-chain discrepancies.

#### Market and Liquidity Analyst

Analyzes spot and derivatives structure, liquidity, volatility, basis, funding, open interest, events, concentration, and alternative explanations.

#### Development Analyst

Analyzes releases, commits, contributors, advisories, dependency changes, program/contract code activity, and repository concentration.

#### Contradiction Investigator

Classifies conflicts as true contradiction, later supersession, different period, definition mismatch, deployment mismatch, publisher claim versus observed state, methodology disagreement, or insufficient evidence.

#### Scenario Analyst

Defines transparent bull, base, and bear assumptions, requests deterministic scenario calculations, and explains sensitivity without presenting scenarios as facts.

### 17.5 Specialist task contract

Input:

```text
task ID
specialist type
precise subquestion
permitted subjects
permitted evidence planes
data cutoff
evidence requirements
initial EvidencePacket
tool policy
context budget
repair limit
materiality
output schema
```

Output:

```text
answer to subquestion
atomic claims
supporting evidence
contradictory evidence
calculation requests
assumptions
uncertainties
missing evidence
alternative explanations
confidence dimensions
recommended follow-up
completion status
```

Completion status:

```text
supported
partially_supported
conflicted
insufficient_evidence
not_applicable
failed
```

### 17.6 Tool policy

Permitted semantic tools:

```text
search_evidence
retrieve_evidence_by_id
retrieve_document_region
retrieve_claim_history
retrieve_structured_observations
retrieve_time_series
request_calculation
request_additional_retrieval
resolve_entity
inspect_source_lineage
submit_specialist_finding
```

Tools enforce workspace, subject, time, source, row/token count, read-only behavior, deadlines, and audit logging.

No specialist receives arbitrary SQL, HTTP, shell, filesystem, RPC, or secret access.

### 17.7 Planning

The planner emits a directed task graph with objectives, coverage, tasks, dependencies, parallel groups, expected outputs, evidence and calculation requirements, stopping conditions, and budget.

The deterministic plan validator checks:

- Mandatory coverage.
- Acyclic dependencies.
- Allowed tools and subjects.
- Temporal constraints.
- Calculation inputs.
- Fan-out.
- Registered schemas.
- Hardware feasibility.

One automatic plan revision is allowed before analyst review.

### 17.8 Context isolation

Each specialist sees only its task, relevant evidence, required metadata, definitions, cutoff, and approved instructions. It does not see unrelated conversation, complete project memory, unsupported worker reasoning, or hidden draft conclusions.

Workers exchange structured findings rather than conversation transcripts.

### 17.9 Due-diligence workflow

```text
freeze dossier snapshot
→ run mandatory branches
→ resolve dependencies
→ calculate
→ investigate conflicts/missing evidence
→ construct assertions
→ draft sections
→ validate
→ review
→ publish versioned dossier
```

Formatting completeness never substitutes for evidence completeness.

### 17.10 Cross-protocol comparison

Rules:

- Shared cutoff wherever possible.
- Missing is not zero.
- Estimates are explicit.
- Incomparable metrics are not ranked.
- Definitions remain visible.
- Freshness is shown by subject.
- Factual ranking and model interpretation remain separate.
- Source quality and missingness are first-class dimensions.
- Document volume cannot inflate confidence.

An overall score is permitted only as a transparent weighted model with visible inputs and sensitivity analysis.

### 17.11 Monitoring-driven research

A new artifact or observation triggers:

```text
entity resolution
→ deterministic change detection
→ dependency impact analysis
→ materiality triage
   ├── immaterial → record
   ├── uncertain → lightweight investigation
   └── material → targeted research graph
→ update affected assertions
→ validate alert
→ request review where required
```

### 17.12 Analyst copilot

The copilot routes requests to quick factual retrieval or full investigation according to materiality and evidence requirements.

It can:

- Answer questions.
- Start investigations.
- Compare subjects.
- Challenge conclusions.
- Inspect evidence.
- Request scenarios.
- Edit assertions.
- Attach notes.
- Approve or reject claims.
- Create monitoring rules.
- Open traces.

Previous model answers are not evidence.

A response packet contains answer, assertions, citations, cutoff, confidence, conflicts, missing evidence, calculations, next action, and originating run.

## 18. Assertion construction, reports, and citations

### 18.1 Two-stage synthesis

#### Stage 1: assertion construction

Validated findings become atomic research assertions. This stage merges duplicates, preserves meaningful differences, identifies temporal changes, separates fact from interpretation, records unsupported portions, attaches evidence, detects cycles, and retains contradictions.

#### Stage 2: prose realization

The writer receives approved assertions and a section outline. It may organize, explain, format, and transition. It may not introduce a new material claim silently.

Any newly generated material claim is extracted after drafting and remains unsupported until validated.

### 18.2 Citation binding

Citations derive from the assertion-evidence graph:

```text
Evidence
→ claim
→ assertion
→ report span
→ rendered citation
```

Each binding records report span, assertion, evidence, citation role, exact locator, excerpt hash, temporal compatibility, entailment state, and rendering metadata.

Citation roles:

```text
direct_support
calculation_input
methodology
qualification
contradiction
background
```

Source locators include:

- PDF page and bounding box.
- Table, row, column, and cell.
- HTML snapshot and DOM region.
- Governance proposal section.
- Git commit or diff range.
- EVM block, transaction, log, call, or storage observation.
- Solana slot, transaction, instruction, or account observation.
- Bitcoin block, transaction, input, or output.
- Market partition and time range.
- Calculation run and input manifest.

Generated summaries, contextual prefixes, and prior model answers cannot be primary citations.

### 18.3 Citation validation

Deterministic validation verifies:

- Evidence exists in the frozen snapshot.
- Locator resolves.
- Artifact hash matches.
- Subject and time are compatible.
- Superseded sources are disclosed.
- Calculation lineage is complete.
- Quoted text matches.
- Citation placement is valid.

A semantic judge returns:

```text
fully_supported
partially_supported
related_but_insufficient
contradicted
temporally_incompatible
wrong_subject
cannot_assess
```

Compound statements with partial support are split, qualified, or rejected.

### 18.4 Citation metrics

- Material-claim coverage.
- All-claim coverage.
- Direct-source ratio.
- Primary-source ratio.
- Independent-source ratio.
- Entailment rate.
- Contradiction rate.
- Stale-citation rate.
- Resolvable-locator rate.
- Calculation-lineage completeness.

### 18.5 Deterministic report validation

Order:

```text
schema
→ assertion/evidence cardinality
→ subject and temporal consistency
→ numerical recalculation
→ units and currency
→ citation resolution
→ section completeness
→ risk taxonomy
→ prohibited unsupported language
```

An LLM judge cannot override deterministic failure.

### 18.6 Numerical validation

Authoritative numbers originate from structured values, validated extraction, deterministic calculation, or explicit analyst assumptions.

Checks include displayed value, formula output, rounding, unit, currency conversion, price time, denominator, sign, percentage-point wording, annualization, and supply definition.

### 18.7 Contradictions and causality

Every material assertion has a conflict matrix containing strongest support, strongest contradiction, temporal explanation, definition mismatch, source-quality differences, unresolved conflict, and analyst resolution.

Causal conclusions require evidence distinguishing alternative hypotheses. Otherwise RSI Atlas uses calibrated language such as “coincided with,” “is consistent with,” or “cannot be isolated from.”

### 18.8 Targeted repair

Validation failures create typed repair tasks such as missing citation, overstrong wording, numerical mismatch, unsupported claim, missing contradiction, stale evidence, or entity mismatch.

Rules:

- Maximum two automatic repair rounds.
- Valid sections remain frozen.
- New evidence requires retrieval.
- Wording cannot change authoritative calculations.
- Repeated failure requires review.
- All versions remain available.

### 18.9 Human review

Required when:

- Material conflict remains.
- Entity resolution is ambiguous.
- Primary evidence is missing.
- A critical claim relies on one weak source.
- Deterministic and semantic validators disagree.
- Judges disagree materially.
- High-severity risk is introduced or removed.
- A published conclusion changes materially.
- A rating is proposed.
- Final report publication is requested.

Review actions:

```text
approve
approve_with_qualification
edit
request_more_evidence
reject
mark_unresolved
supersede_previous_decision
```

Review events are immutable.

### 18.10 Publication gate

Required conditions:

```text
schema valid
data cutoff frozen
required sections present
mandatory evidence coverage satisfied
material calculations validated
material citations resolvable
citation entailment threshold passed
contradictions disclosed
limitations disclosed
prompt-injection checks passed
evaluation thresholds passed
review requirements satisfied
reproducibility manifest complete
```

Outcomes:

```text
publish
publish_as_degraded
return_for_targeted_repair
await_analyst_review
reject
```

A finalized investment-committee memo cannot silently publish as degraded.

### 18.11 Report editing

Edits trigger validators by semantic impact:

```text
stylistic edit       citation may remain valid
numeric edit         deterministic revalidation
meaning change       assertion version and revalidation
new uncited claim    analyst-authored unsupported state
removed qualification contradiction/risk revalidation
timeframe change     temporal revalidation
```

The editor distinguishes validated, analyst-modified, unsupported, citation-at-risk, contradicted, stale, and pending-calculation text.
## 19. Structured data and collectors

### 19.1 Evidence planes

```text
Document intelligence
On-chain intelligence
Market intelligence
Protocol intelligence
Development intelligence
Governance and event intelligence
```

All sources follow:

```text
raw source
→ immutable observation
→ validated normalized record
→ entity resolution
→ time-aligned feature
→ claim/evidence object
→ research graph
→ memo, comparison, alert, answer, or signal
```

### 19.2 Scope policy

Collection is watchlist-scoped rather than global.

The initial complete release continuously monitors selected:

- Assets and protocols.
- Contracts, programs, treasuries, wallets, and repositories.
- Exchange instruments.
- Governance systems.
- Protocol APIs.
- Network metrics needed for Bitcoin, EVM, and Solana context.

Historical backfill is an explicit bounded job.

### 19.3 Collector contract

A collector supports discovery, bounded collection, cursor checkpointing, and health.

A definition declares source family, provider, networks or venues, acquisition mode, authentication, network allowlist, schema, rate limits, retry, cursor, retention, usage policy, backfill support, and lifecycle status.

Acquisition modes:

```text
snapshot
incremental_poll
websocket_stream
local_node_subscription
filesystem_import
bundle_import
on_demand
```

### 19.4 Collector graph

```text
START
→ load definition
→ acquire lease
→ check network/source policy
→ load cursor
→ discover range
→ build bounded plan
→ collect batch
→ persist raw envelopes
→ validate transport and sequence
→ decode
→ normalize
→ run data quality
   ├── invalid → quarantine
   ├── conflicted → retain and escalate
   └── valid
→ publish observation batch
→ advance cursor
→ emit data events
→ schedule features
→ evaluate monitoring rules
→ END
```

A PostgreSQL-backed local scheduler stores job, lease, expiry, heartbeat, attempt, priority, resource class, idempotency key, schedule, and dependencies.

### 19.5 Raw envelope

Every provider response is persisted before decoding with collector, provider, request fingerprint, request and response times, event-time hint, cursors, transport status, content information, payload hash, payload location, size, source schema, network-policy decision, and redacted request metadata.

Raw payloads are immutable, compressed, replayable, and free of credentials.

### 19.6 Rate limits and retries

Each collector has independent request weight, quota, reset, retry-after, concurrency, backoff, and circuit-breaker state.

Rules:

- Provider-directed retry timing is respected.
- Schema failures are not retried as transport failures.
- WebSocket reconnection triggers sequence reconciliation.
- Repeated provider defects open a circuit breaker.
- Backfills have lower priority than current monitoring.
- Retries preserve logical request identity.

## 20. Multi-chain normalization

### 20.1 Shared and chain-specific models

Shared layer:

```text
Asset
Protocol
Organization
WalletIdentity
Observation
DerivedMetric
Claim
Evidence
ResearchEvent
SourceLineage
```

Chain-specific models remain separate:

```text
EVM       accounts, calls, logs, proxies, token state, DeFi state
Solana    accounts, owners, instructions, PDAs, SPL state, programs
Bitcoin   UTXOs, scripts, inputs/outputs, fees, mining, clusters
```

RSI Atlas does not force these semantics into one generic transaction table.

### 20.2 Pinned identity

```text
EVM      chain_id + block_number + block_hash
Solana   cluster + slot + blockhash + commitment
Bitcoin  network + block_height + block_hash
```

No published “latest” state exists without a pinned reference.

### 20.3 EVM

Collected evidence may include:

- Block headers.
- Transactions and receipts.
- Logs.
- Bytecode.
- Selected storage.
- Approved read-only calls.
- Native and token balances.
- Proxy and implementation state.
- Protocol-specific state.
- Gas and network observations.

Every record carries chain, block, hash, transaction and log identity where applicable, contract, finality, provider, and retrieval time.

Finality states:

```text
observed
provisional
safe
finalized
orphaned
```

Reorganization handling marks affected observations orphaned, invalidates dependent features, recollects replacement data, and identifies affected claims and reports. Historical snapshots are retained with later orphaning status.

ABI decoding retains raw topics/data, decoded fields, decoder version, ABI hash, and confidence. Verified, repository-derived, manually supplied, inferred, and unresolved ABI sources remain distinct.

Detectors include implementation, admin, role, delay, emergency control, supply, mint/burn, treasury, governance execution, pause, fee, oracle, bridge, and bytecode changes.

### 20.4 Solana

Collected evidence may include:

- Slots and blocks.
- Transactions and signatures.
- Top-level and inner instructions.
- Program logs.
- Account state.
- Program accounts.
- SPL Token and Token-2022 state.
- Mints and supply.
- Address lookup tables.
- Upgradeable-loader state.
- Vote and stake observations.

Every record carries cluster, slot, blockhash, signature, instruction identities, account, owner, commitment, provider, and retrieval time.

Raw account bytes are retained alongside lamports, owner, executable state, data length, slot, decoder version, and decoded representation.

Commitment states:

```text
processed
confirmed
finalized
invalidated
```

Material reports use finalized observations unless explicitly describing provisional activity.

Detectors include program upgrade, upgrade authority, immutability, mint/freeze authority, supply anomaly, treasury transfer, governance execution, validator concentration, owner change, configuration change, and unexpected invocation pattern.

### 20.5 Bitcoin

Bitcoin Core is the primary Bitcoin evidence source.

Reference profile:

```text
full validation
localhost or Unix-controlled RPC
no wallet required
transaction index enabled where storage permits
ZMQ event triggers
optional Electrum-compatible query index
```

Collected evidence may include:

- Headers, blocks, transactions.
- Inputs, outputs, scripts, and witness data.
- UTXO state.
- Mempool state.
- Fee estimates.
- Chain statistics.
- Difficulty and mining observations.
- Selected watched entities.

Every record carries network, height, block hash, transaction identity, input/output index, confirmations, main-chain status, node version, and retrieval time.

ZMQ is a wake-up signal only; authoritative data is retrieved and verified through RPC.

Detectors include fee regime, mempool congestion, watched movement, UTXO consolidation, labelled exchange/ETF flows where methodology permits, miner flows, difficulty/network changes, large clusters, and software or protocol development.

Address clustering is explicitly an inference.

### 20.6 Provider disagreement

EVM and Solana support primary, secondary, optional tertiary verification, and local cache.

Quality states:

```text
single_source
cross_verified
degraded
conflicted
unavailable
invalid
```

Conflicted data cannot support high-confidence calculations until resolved or qualified.

## 21. Market, protocol, governance, and development planes

### 21.1 Market identity

A canonical instrument records venue, venue-native symbol, base, quote, settlement, type, multiplier, expiry, margin, tick, quantity step, status, validity period, and canonical asset mapping.

Spot, perpetual, future, option, DEX pool, wrapped asset, and synthetic asset remain distinct.

### 21.2 Streaming market lifecycle

```text
load instrument definition
→ fetch REST snapshot
→ connect WebSocket
→ buffer deltas
→ align sequence
→ apply deltas
→ verify continuity
   ├── gap → discard and resnapshot
   └── valid → publish normalized state
```

Times include exchange event, match, receive, normalize, and publish.

### 21.3 Market retention

Watchlist instruments may retain raw trades, best bid/ask, selected depth deltas, periodic snapshots, funding, and derivatives. Non-watchlist instruments use lower-frequency reference data.

Raw depth has short retention, raw trades medium retention, aggregated bars and features long retention. Compaction requires a validated manifest.

### 21.4 Market quality

- Sequence and trade-ID continuity.
- Positive price and quantity.
- Ordered non-crossed book.
- Time monotonicity.
- Valid instrument definition.
- Decimal precision.
- Volume reconciliation.
- REST/WebSocket reconciliation.
- Duplicate and outlier detection.
- Stale-stream detection.

Authoritative amounts use fixed precision, not binary floating point.

### 21.5 DEX evidence

DEX events remain chain evidence first. Derived trades retain chain snapshot, transaction/instruction reference, pool, assets, raw and normalized quantities, price, fees, decoder, and calculation versions.

### 21.6 Protocol metrics

Each metric specifies protocol, definition, value, unit, period, methodology, source, estimated status, quality, and lineage.

Terms such as “revenue” must define gross/net, user fees, protocol retention, token-holder distribution, incentives, chain coverage, product coverage, currency conversion, and aggregation.

Different definitions remain separate.

### 21.7 Governance

Governance records include proposal, vote, delegation, quorum, execution, cancellation, veto, emergency action, off-chain signal, forum discussion, and multisig action.

On-chain execution and off-chain discussion connect through explicit proposal identities.

Detectors include quorum, voting period, delegation concentration, veto role, execution mismatch, emergency power, passed-not-executed, and off-chain/on-chain divergence.

### 21.8 Development

Collected records include repository, commit, tag, release, contributor, issue, pull request, security advisory, dependency manifest, workflow result, ownership change, and archive/delete event.

Features distinguish code, docs, generated output, bots, dependency automation, merges, releases, and human activity. Raw commit counts are not treated as quality.

Detectors include release, advisory, vulnerability, maintainer concentration, archive, sustained activity decline, deployment-related code change, undocumented release, and ownership change.

## 22. Observation, quality, and storage

### 22.1 Observation header

Common fields:

```text
observation ID and type
subjects
source artifact
raw envelope
event time
available time
collected time
normalized time
valid time
system time
quality
finality
normalizer version
schema version
```

Payloads are discriminated, source-specific Pydantic models.

### 22.2 Data-quality contracts

Each dataset declares schema, uniqueness, required fields, ranges, temporal and sequence checks, cross-field invariants, reconciliation, freshness, completeness, quarantine, and severity.

Quality dimensions:

```text
validity
completeness
uniqueness
consistency
timeliness
sequence integrity
source agreement
finality
entity certainty
methodology stability
```

Invalid data is quarantined with reasons rather than discarded.

### 22.3 Corrections and backfills

Corrections create new normalized versions linked through supersession and changed-field metadata.

Backfills are bounded, budgeted, partitioned, resumable, completeness-validated, and followed by dependent recomputation and before/after comparison.

Unknown source schema changes pause cursor advancement and require decoder review. An LLM may not invent a new production decoder.

### 22.4 Local storage

PostgreSQL stores operational and recent normalized state, feature registry, latest values, monitoring, workflows, and evaluation.

Parquet stores large histories partitioned by source, venue/network, subject/instrument, and date or block bucket.

Every partition has schema, min/max times, row count, source coverage, content hash, raw-envelope range, writer version, and quality result.

The immutable artifact store holds raw API/RPC payloads, stream segments, HTML/PDF, chain bundles, repository archives, parser outputs, reports, and reproduction packages.

## 23. Feature engineering and research signals

### 23.1 Feature definition

A feature declares identity, entity type, grain, value type, unit, source requirements, dependencies, lookback, availability delay, implementation version, null policy, quality policy, owner, and lifecycle status.

A value stores subject, effective and available time, value, unit, input manifest, calculation run, quality, freshness, and coverage.

### 23.2 Feature families

#### Market

Returns, volatility, volume, turnover, spread, depth, imbalance, impact, funding, basis, open-interest change, liquidations, dispersion, concentration.

#### Bitcoin

Fees, mempool, transactions, UTXO-age distributions, mining and difficulty, watched flows, and explicitly defined network metrics.

#### EVM

Addresses, transactions, gas, contract interactions, transfers, supply, holders, treasury, protocol flows, admin and upgrade events.

#### Solana

Accounts, program invocations, compute use, token supply, holders, staking/validators, upgrades, treasury, and protocol account state.

#### Protocol

TVL, fees, revenue, incentives, net revenue, treasury, runway, activity, capital efficiency, value-accrual ratios, revenue-to-emissions.

#### Governance

Participation, quorum margin, delegation and voter concentration, proposal outcomes, execution delay, emergency-power frequency, governance change.

#### Development

Active contributors, maintainer concentration, release cadence, material activity, advisories, dependency changes, issue latency, code-to-deployment linkage.

#### Document intelligence

Risk-disclosure changes, tokenomics amendments, new findings, contradiction count, evidence freshness, source coverage, and document-version materiality.

### 23.3 Point-in-time correctness

A feature is eligible only when:

```text
feature.available_time <= investigation.as_of
```

Point-in-time joins use identity, event/effective time, available time, source validity, and methodology version.

Temporal tests include delayed governance, backfills, revised metrics, late releases, backdated documents, and reorganizations.

### 23.4 Feature graph

```text
new observation batch
→ identify affected definitions
→ resolve dependency DAG
→ compute leaves
→ validate
→ compute dependents
→ compare previous state
→ publish versions
→ evaluate monitoring
```

Cycles are rejected.

### 23.5 Promotion

Feature lifecycle:

```text
experimental
candidate
production
deprecated
retired
```

Promotion requires economic definition, tests, leakage tests, coverage, missingness, stability, reconciliation, review, performance budget, and documentation.

### 23.6 Research signals

Signals are evidence-backed research events, not orders.

Examples:

- Liquidity deterioration.
- Dilution acceleration.
- Treasury threshold.
- Governance concentration increase.
- Expanded admin privilege.
- Upgrade detection.
- Development decline.
- Revenue/incentive divergence.
- Market/on-chain divergence.
- Document claim contradicted by observed state.

A signal cannot place a trade, sign a transaction, or access an exchange account.

## 24. Continuous monitoring

### 24.1 Monitoring flow

```text
published artifact/observation
→ deterministic change detector
→ rule matcher
→ materiality screen
→ dependency lookup
→ semantic triage if needed
→ targeted research graph
→ alert validation
→ analyst notification
```

Rule types:

```text
threshold
rate of change
rolling anomaly
structural break
sequence event
state transition
document diff
schema diff
contract/program diff
cross-source disagreement
composite
scheduled reevaluation
```

### 24.2 Cadence

```text
Immediate   new block, watched event, selected market stream, source health
Minutes     market state, treasury, operational state, governance execution
Hourly      protocol metrics, liquidity, funding/OI, GitHub, reconciliation
Daily       documents, forums, development summaries, feature and staleness review
Scheduled   backfills, dossiers, comparisons, large evaluations
```

Critical monitoring retains capacity during heavy research and backfills.

### 24.3 Materiality

Materiality combines magnitude, duration, confidence, source reliability, subject importance, dependency impact, rarity, and analyst thresholds.

Outcomes:

```text
record_only
low
medium
high
critical
requires_more_evidence
```

A model may classify and explain but cannot alter observed measurements or suppress a deterministic critical event.

### 24.4 Alert model

An alert stores rule, subject, severity, detected and event times, previous and current state, change summary, deterministic measurements, evidence, affected assertions/reports, confidence, missing evidence, status, and analyst decisions.

Lifecycle:

```text
detected
triaging
validated
awaiting_review
published
acknowledged
investigating
resolved
dismissed
superseded
```

Deduplication uses subject, rule, underlying event identity, time window, and state transition.

### 24.5 Dependency impact

```text
changed observation
→ calculation
→ feature
→ claim
→ assertion
→ report/comparison/alert
```

The engine chooses no action, stale marking, recomputation, assertion revalidation, dossier staleness, targeted section regeneration, alert, or review.

---

## 25. Local model platform

### 25.1 Selected architecture

RSI Atlas uses a capability-routed multi-runtime model plane:

```text
Atlas Model Router
├── Apple Foundation Models
├── MLX reasoning provider
├── OpenAI-compatible local provider
├── embedding provider
├── reranking provider
├── vision provider
└── deterministic services
```

Application workflows target RSI Atlas interfaces rather than a runtime-specific API.

### 25.2 Provider contract

Each provider exposes capabilities, health, generate, stream, and unload.

A `ModelRequest` includes request ID, task definition, prompt and schema versions, structured input, allowed tools, generation policy, context/output limits, deadline, reproducibility, privacy class, and trace context.

A `ModelResponse` includes model artifact, provider/runtime version, output, tool calls, validation, token counts, latency, finish reason, retries, warnings, and execution manifest.

Capabilities are declared and tested:

```text
text_generation
structured_generation
tool_calling
vision
streaming
long_context
reasoning
embeddings
reranking
multilingual
deterministic_sampling
```

### 25.3 Apple Foundation Models

Apple Foundation Models are the preferred on-device tier for light semantic work.

Approved tasks:

- Intent and document classification.
- Section and risk taxonomy.
- Entity candidate extraction.
- Query routing.
- Chunk labelling.
- Simple relevance grading.
- Concise evidence summarization.
- Metadata normalization suggestions.
- Lightweight change classification.

Not authoritative for:

- Final investment conclusions.
- Financial calculations.
- Complex contradiction adjudication.
- Critical citation validation.
- Primary report-level judging.
- Unbounded planning.
- Arbitrary tool execution.

The production app initially prefers a Swift-hosted provider service. A Python provider is permitted for headless development and parity testing.

Every execution records macOS build, framework version, reported context information, availability, locale, prompt compatibility, schema, and generation settings.

After a relevant OS/model update:

```text
mark Apple prompt configurations unverified
→ run capability smoke tests
→ run Apple-specific regression suite
→ compare with accepted baseline
   ├── pass → re-enable
   └── fail → local fallback and review
```

### 25.4 Reasoning model daemon

`atlas-modeld` provides a stable local boundary for larger models:

- Unix socket.
- Streaming.
- Structured-output enforcement.
- Tool-call parsing.
- Cancellation and deadlines.
- Load/unload.
- Prompt cache.
- Resource measurement.
- Provider plugins.

Initial plugins:

```text
MLXReasoningProvider
OpenAICompatibleReasoningProvider
```

MLX is performance-preferred where benchmarked. The OpenAI-compatible provider is the compatibility and local-Codex path.

### 25.5 Task qualification

Models are approved per task, not globally.

Examples:

```text
research_planner
citation_judge
report_writer
parser_quality_judge
entity_resolver
```

Each profile defines capability requirements and benchmark thresholds.

### 25.6 Retrieval and vision models

Embedding, reranking, and vision remain separate services with independent artifacts, batching, caches, evaluation, loading, and fallback.

Vision receives selected pages or regions only.

### 25.7 Resource arbiter

The arbiter controls model residency, memory reservations, priority, queue admission, thermal state, swap pressure, free-memory reserve, and emergency unloading.

Every heavy job acquires a typed resource lease.

Priority order:

1. UI responsiveness.
2. Database transaction integrity.
3. Critical chain and monitoring collection.
4. Analyst-requested research.
5. Background evaluation.
6. Historical backfill.
7. Idle model residency.

The system rejects new heavy work before entering unsafe memory pressure.

### 25.8 Model registry

A `ModelArtifact` records immutable hash, provider family, upstream ID, architecture, parameter class, quantization, tokenizer hash, context configuration, license, source manifest, local path, capability results, benchmarks, approved tasks, and lifecycle.

Lifecycle:

```text
imported
quarantined
benchmarking
candidate
production
degraded
deprecated
retired
rejected
```

### 25.9 Prompt registry

Prompts are versioned software artifacts with system instruction, schemas, tools, context policy, supported/forbidden models, evaluation suite, failure behavior, owner, change rationale, and lifecycle.

A prompt change creates a candidate version and requires evaluation before promotion.

### 25.10 Model supply-chain controls

- Dedicated acquisition process.
- Approved sources.
- License inspection.
- Content hashes.
- Format checks.
- No arbitrary remote code.
- Quarantine.
- Offline capability tests.
- Resource benchmark.
- Manual promotion.
- Network-disabled inference.
- Signed offline bundles.

## 26. Evaluation system

### 26.1 Local evaluation lifecycle

```text
versioned datasets
→ code, model, and human evaluators
→ experiments
→ paired comparison
→ promotion gate
→ sampled production evaluation
→ failure mining
→ regression datasets
```

### 26.2 Dataset registry

Each dataset records ID, version, purpose, task family, frozen source snapshot, examples, splits, annotation policy, licensing/sensitivity, lineage, and status.

Splits:

```text
development
calibration
regression
adversarial
holdout
shadow-production
```

Holdout data is not exposed to prompt tuning.

Dataset families cover parsing, retrieval, extraction, agents, generation, citations, numerical reasoning, abstention, and security.

### 26.3 Evaluator order

```text
1. schema
2. deterministic business rules
3. exact/numerical
4. retrieval/citation
5. statistical
6. LLM judge
7. human review
```

A later evaluator cannot erase an earlier deterministic failure.

### 26.4 LLM judge suite

- Groundedness.
- Citation entailment.
- Evidence completeness.
- Contradiction coverage.
- Risk calibration.
- Abstention.
- Comparative fairness.
- Report coherence.
- Prompt-injection response.

Each judge has a narrow rubric, masked inputs, typed output, model/prompt versions, evaluation suite, and known limitations.

### 26.5 Judge calibration

Measured against human labels:

```text
agreement
false acceptance
false rejection
precision/recall by defect
stability
position bias
verbosity bias
citation-count bias
source-authority sensitivity
self/model-family preference
```

Pairwise evaluations randomize order, hide identities, allow ties, repeat borderline cases, and report confidence intervals.

Preferred generator and judge families differ. If the same family is used, RSI Atlas records limited independence and strengthens deterministic and human checks.

### 26.6 Experiment manifest

An experiment freezes source snapshot, graph, model assignments, prompts, parser, chunker, embeddings, reranker, retrieval, context policy, judges, sampling, and hardware.

It records quality metrics, failure classes, load time, first-token latency, throughput, peak memory, retries, and variance.

### 26.7 Statistical comparison

Promotion reports:

- Paired differences.
- Bootstrap confidence intervals.
- Slice results.
- Effect sizes.
- Non-inferiority.
- Critical-failure counts.

A mean improvement cannot hide a regression in future-information leakage, wrong-entity retrieval, unsupported citations, numerical correctness, or access control.

### 26.8 Promotion gates

Examples of hard requirements:

```text
critical deterministic failures     0
material citation coverage          100%
critical numerical correctness      100%
historical leakage                  0
cross-workspace leakage             0
retrieval quality                    non-inferior or better
judge false-acceptance               below policy threshold
memory and p95 latency               within hardware budget
unrecoverable run rate               below threshold
```

Outcomes:

```text
promote
promote_for_selected_task_only
continue_shadow_evaluation
reject
require_human_review
```

### 26.9 Production evaluation

All runs receive inexpensive deterministic checks. Semantic judges are sampled locally or triggered by severity, new versions, degraded retrieval, disagreement, or analyst correction.

A production failure becomes a local labelled regression case with frozen inputs, expected behavior, actual behavior, validators, and source manifest.

## 27. Observability

### 27.1 Architecture

OpenTelemetry-compatible trace context spans Swift, Python, LangGraph, workers, collectors, models, database, and Codex.

```text
application and workers
→ local collector
→ redaction/normalization/batching/sampling
→ local trace, metric, log, and artifact stores
```

No telemetry leaves the machine in strict mode.

### 27.2 Trace topology

One analyst action creates one distributed trace:

```text
Swift command
→ API command
→ LangGraph run
   ├── planning
   ├── retrieval
   ├── specialist workers
   ├── calculations
   ├── synthesis
   └── publication gate
```

Context propagates through sockets, jobs, graph state, model requests, database outbox, and Codex tasks.

### 27.3 Span types

```text
atlas.command
atlas.workflow
atlas.langgraph.node
atlas.agent
atlas.model.generate
atlas.model.embed
atlas.model.rerank
atlas.tool
atlas.retrieve
atlas.parse
atlas.collect
atlas.calculate
atlas.validate
atlas.evaluate
atlas.review
atlas.publish
atlas.codex.turn
atlas.codex.command
```

Spans store compact metadata and artifact references, not large documents.

### 27.4 Payload modes

```text
Metadata-only  hashes, sizes, identifiers, scores, timings
Standard       metadata + sanitized encrypted local artifacts
Debug          full model-visible payloads, short retention
Evaluation     frozen inputs, outputs, references, and manifests
```

RSI Atlas stores model-visible inputs, outputs, tools, and structured findings. Hidden chain-of-thought is not a required artifact.

### 27.5 Storage and retention

PostgreSQL stores recent trace indexes, summaries, errors, evaluation links, and operational metrics. Parquet stores history and aggregates. The artifact store contains sanitized model payloads and reproduction bundles.

High-volume low-value spans have short retention; failed traces, published-report traces, and experiments have longer retention.

### 27.6 Metrics

Metrics include application latency, queues, worker health, model load and throughput, memory and swap, retrieval counts and quality, ingestion throughput and fallback, agent completion and repair, evaluation regressions, disk, CPU, thermal, and database health.

### 27.7 LangSmith compatibility

RSI Atlas implements LangSmith-like concepts locally:

```text
Project          local trace project
Run              span/workflow run
Thread           investigation thread
Dataset          evaluation dataset
Example          evaluation example
Experiment       experiment run
Feedback         evaluation result
Annotation Queue analyst review queue
```

Instrumentation may emit compatibility attributes for a future exporter. The exporter is optional, absent or disabled in offline mode, blocked by zero-egress policy, and cannot activate implicitly.

Self-hosted LangSmith is not a dependency of the reference workstation.

## 28. Codex engineering plane

### 28.1 Boundary

Codex assists software engineering and operations. LangGraph remains the production research orchestrator.

Approved uses:

- Reproduce a failing trace.
- Generate or update tests.
- Inspect parser and retrieval regressions.
- Compare experiment outputs.
- Propose a targeted patch.
- Run local tests and static analysis.
- Prepare migrations.
- Update generated clients.
- Review dependency changes.
- Produce release notes.

Prohibited authority:

- Query production research data freely.
- Access Keychain.
- Change network policy.
- Promote models or evaluations.
- Publish reports.
- Merge or push automatically.
- Deploy.
- Trade or sign.

### 28.2 Integration

Interactive integration uses Codex App Server through a locally controlled transport and generated/contract-tested schemas.

Automated jobs use structured non-interactive event output where supported.

The selected Codex version and local provider must pass compatibility tests for tool calls, streaming, command events, file-change events, approvals, and session handling before production use.

Because local/custom provider behavior can vary by Codex and provider version, RSI Atlas treats local Codex support as a qualified component, not an assumed invariant.

### 28.3 Worktree isolation

Codex receives:

```text
isolated Git worktree
synthetic fixtures
explicitly approved regression cases
sanitized trace bundle
generated schemas
test database
temporary build output
```

Denied:

```text
production credentials
raw private documents
analyst notes
complete data archives
Keychain
release signing keys
live collectors
```

### 28.4 Reproduction bundle

```text
failure summary
source/code versions
sanitized structured inputs
expected and actual behavior
deterministic validator results
selected trace spans
approved fixtures
environment manifest
permitted commands
```

### 28.5 Approval policy

- Read source in worktree: allowed.
- Safe inspection commands: policy allowed.
- File changes: visible patch.
- Tests: allowed within limits.
- Dependency install: explicit approval.
- Network: denied in strict mode.
- Production database: impossible by permissions.
- Commit: explicit approval.
- Merge/push: outside automated authority.

Every command and file change enters the RSI Atlas trace model.

### 28.6 Quality gate

Codex output remains a candidate patch and must pass static analysis, unit, integration, security, evaluation regression, performance/memory checks, and human review.
## 29. Security architecture

### 29.1 Security outcomes

- No unauthorized external egress.
- No arbitrary network access from agents or models.
- No arbitrary code execution from documents or model artifacts.
- No silent modification of raw evidence.
- No cross-workspace access.
- No untraceable material conclusion.
- No unaudited publication.
- No unsigned application/runtime update.
- No credentials in traces or prompts.
- No trading, signing, or wallet authority.

### 29.2 Threat sources

```text
malicious publisher or document
compromised website/RPC/API/repository
prompt injection
poisoned model/tokenizer
compromised dependency
malicious local unprivileged process
analyst error
model error
parser/normalizer defect
update compromise
credential theft
filesystem/database corruption
faulty Codex patch
```

The initial trust boundary assumes the logged-in macOS account is trusted. It does not claim resistance to root compromise, kernel compromise, an unlocked stolen session, or compromise of signing credentials.

### 29.3 Trust zones

```text
1 Native UI
2 Control plane
3 Core research engine
4 Untrusted-content processing
5 Model execution
6 Structured-data collection
7 Persistence
8 Engineering/Codex
```

Each signed process receives only required network, file, secret, and command capabilities.

### 29.4 Offline and monitored components

The base offline distribution excludes remote collectors and automatic network update checks.

The monitored-research capability is a separately controlled component with allowlisted network access and a dedicated quarantine drop zone. It cannot read private documents, analyst notes, reports, prompts, traces, or Codex worktrees.

### 29.5 macOS hardening

The intended release posture includes:

- Native SwiftUI app.
- App Sandbox where compatible with required functionality.
- Hardened Runtime.
- Developer ID signing.
- Notarization.
- Per-user background service rather than a root daemon.
- App Group or equivalent controlled shared container.
- User-selected file access.
- Narrow Keychain sharing.
- Process-specific entitlements.
- No global relaxation merely because one model runtime needs a special capability.

Release builds must not contain debugging entitlements or unexpected network authority.

### 29.6 IPC security

Sensitive control calls use an authenticated local control channel. Data-plane sockets use owner-only permissions, per-session names, peer checks, short-lived capabilities, deadlines, size limits, and versioned requests.

Capabilities specify actor, workspace, commands, subjects, issue/expiry times, nonce, and issuer.

### 29.7 Secrets and data classification

Keychain stores scoped collector credentials, database credentials, backup keys, workspace keys, and update state.

Classes:

```text
Public        public sources and chain data
Internal      indexes, features, evaluations
Confidential  private PDFs, analyst notes, reports
Secret        credentials and signing/encryption keys
```

Secrets are never placed in environment files, graph state, prompts, traces, raw envelopes, Codex bundles, or ordinary exports.

FileVault and a protected macOS account are mandatory for the live searchable database. Sensitive raw artifacts and debug payloads may additionally use workspace-level envelope encryption.

### 29.8 Untrusted content

Parser workers receive one read-only artifact, an empty staging directory, no network, no Keychain, no parent database connection, sanitized environment, and bounded resources.

Archive handling enforces expanded-size, file-count, nesting, traversal, symlink, and MIME limits.

HTML scripts are never executed; active content is stripped and remote resources are not fetched automatically.

### 29.9 Query and shell controls

Models emit typed structured query requests compiled by deterministic services against read-only database roles. They never execute arbitrary SQL.

Production research agents have no shell.

Only the isolated Codex engineering environment runs commands, under policy and without production credentials or network in strict mode.

### 29.10 Supply chain

- Python dependencies locked with hashes.
- Swift packages pinned.
- Actions pinned for any public CI.
- Container images pinned by digest where used.
- No runtime dependency resolution.
- Local release wheelhouse.
- License policy.
- SBOM.
- Hash-pinned models and tokenizers.
- No unreviewed remote code.
- Signed release and model manifests.

## 30. Testing and quality gates

### 30.1 Test pyramid

```text
release acceptance
security and recovery
end-to-end application
fault injection and soak
LLM/retrieval evaluation
integration and contract
property/golden/unit
static analysis and schema checks
```

### 30.2 Static analysis

Python:

```text
Ruff
mypy or Pyright
format checking
dependency audit
secret scanning
license checks
unsafe deserialization checks
```

Swift:

```text
compiler warnings as errors
swift-format
SwiftLint where useful
strict concurrency
entitlement inspection
dependency audit
```

Cross-language:

```text
OpenAPI/JSON Schema consistency
Pydantic/Codable compatibility
migration linting
SBOM and license validation
```

### 30.3 Unit and property testing

Unit tests cover schemas, identities, arithmetic, time, calculations, source policies, chunking, fusion, context budgets, citations, confidence, monitoring, deduplication, and capabilities.

Property tests enforce immutability, stable identity, decimal round trips, atomic publication, idempotent replay, monotonic availability, no historical leakage, citation resolvability, and valid workspace transitions.

Chain properties enforce exact event/output identities and prevent orphaned state from supporting finalized conclusions.

### 30.4 Contract tests

Contracts cover Swift/control plane, Swift/engine, engine/worker, engine/model provider, database, collector/source, normalizer/schema, Codex/native client, update manifest, and backup manifest.

Breaking changes require a new version, migration, compatibility policy, old-client behavior, and rollback test.

### 30.5 Golden tests

Golden fixtures cover canonical PDF output, tables, RPC normalization, order books, chunking, retrieval candidates, citations, and report exports.

Intentional changes require explicit before/after review.

### 30.6 Integration environment

Real local integration may include:

```text
PostgreSQL + pgvector
DuckDB + Parquet
LangGraph checkpointing
embedding and reranking models
selected reasoning model
PDF parsers
Bitcoin Core regtest
local EVM chain
Solana test validator or approved fixtures
OpenTelemetry collector
Codex local provider
```

### 30.7 Security tests

- Malformed PDFs and parser fuzzing.
- Archive bombs and traversal.
- Malicious HTML.
- Prompt and indirect tool injection.
- Citation spoofing.
- Workspace tampering.
- Socket impersonation and capability replay.
- Model/update/backup tampering.
- SQL and query-template bypass.
- SSRF, redirect, and unapproved-host attempts.
- Credential redaction.
- Codex sandbox escape attempts.

Offline release acceptance records no external DNS, TCP, telemetry, model, update, or resource request.

### 30.8 Fault injection

Faults include process termination, database loss, telemetry loss, network interruption, rate limits, schema break, disk pressure, read-only filesystem, model OOM, corrupted Parquet, index corruption, migration failure, chain reorganization, and Apple-model unavailability.

Expected behavior is no raw evidence loss, no partial publication, checkpoint recovery, bounded retry, clear degradation, repair/rebuild, analyst notification, and a reproducible incident bundle.

### 30.9 Native UI tests

- Swift unit and integration tests.
- Accessibility identifiers and VoiceOver.
- Keyboard-only navigation.
- Reduce Motion.
- Light/dark modes.
- Large text.
- Multi-window state.
- Drag-and-drop.
- Report undo/redo.
- Screenshot regression for high-value views.

### 30.10 Performance qualification

Every production release is tested on 24 GB and 32–36 GB profiles.

Measures include launch, database startup, model load, first token, throughput, embeddings, parsing, OCR, retrieval p50/p95, report generation, memory, swap, thermal, disk, and power behavior.

Workloads include a single PDF, a 500-page report, scanned audit, multi-document dossier, three-subject comparison, retrieval benchmark, monitoring during research, judge run, and Codex session.

### 30.11 CI lanes

#### Pull request

Static analysis, unit, property, schema, migration, secret, dependency/license, Swift build, and Python build using public/synthetic fixtures.

#### Integration

Apple Silicon self-hosted runner with local services, parsers, model smoke tests, recovery, Swift/Python contracts, collector fixtures, and Codex compatibility.

#### Evaluation

Retrieval, agents, citations, judges, adversarial security, memory, and latency.

#### Release

Dedicated release Mac: clean checkout, locks, full suites, SBOM, nested signing, entitlement audit, notarization, stapling, Gatekeeper, clean install, upgrade, rollback, backup, and restore.

### 30.12 Hard release blockers

- Failing deterministic test.
- Critical/high unreviewed vulnerability.
- Unknown executable or entitlement.
- Invalid signature or notarization.
- SBOM mismatch.
- Migration or restore failure.
- Critical evaluation regression.
- Future-information or cross-workspace leakage.
- Unsupported material citation.
- Critical numerical error.
- Zero-egress failure.
- Unrecoverable worker crash.
- Irreversible update without verified backup.
- Codex policy bypass.

## 31. Packaging and release

### 31.1 Distribution

RSI Atlas is distributed outside the Mac App Store as a Developer ID-signed and notarized macOS application.

The selected package is a native app with an embedded isolated Python runtime and signed helpers. It does not depend on system Python, Homebrew, global packages, or a complete container runtime.

### 31.2 Bundle intent

```text
RSI Atlas.app
├── SwiftUI executable
├── native frameworks
├── control/Foundation Models services
├── engine and worker launchers
├── signed local database runtime
├── embedded isolated CPython
├── signed native extensions
├── application Python archive
├── migrations
├── prompts and schemas
├── manifests, licenses, and SBOM
└── diagnostic tooling
```

Exact placement follows final macOS signing and service-management requirements.

### 31.3 Embedded Python rules

- Isolated configuration.
- No user site packages.
- No `PYTHONPATH`.
- Fixed `sys.path`.
- No import from current directory.
- Read-only packaged modules.
- Manifest verification.
- No runtime pip or compiler.
- No arbitrary plugins.

### 31.4 PostgreSQL

A pinned local PostgreSQL + pgvector runtime uses a per-user cluster, Unix socket only, Keychain credential, checksums where supported, and versioned migrations.

Durable data remains outside the application bundle.

### 31.5 External large components

Model weights, Bitcoin blockchain data, large historical datasets, Bitcoin Core, and Codex may remain separately managed or imported through signed component bundles.

### 31.6 Signing

Nested code signs inside-out: libraries, Python extensions, helpers, services, frameworks, app, archive.

Release verification includes strict code-signature checks, entitlement diff, team identity, timestamp, Gatekeeper, notarization log, ticket stapling, and clean-user launch.

### 31.7 Update classes

- Application/runtime.
- Models/tokenizers.
- Research configuration.
- Database/schema migrations.

These are independently versioned and promoted.

### 31.8 Update flow

```text
verify signatures/manifests
→ check compatibility, disk, backup
→ pause new workflows
→ checkpoint graphs
→ create pre-update backup
→ stop services
→ install
→ start compatibility mode
→ expand-only migrations
→ health/smoke tests
   ├── pass → activate
   └── fail → rollback
→ resume
```

Monitored installations may use a signed native updater. Offline installations import a signed update bundle manually.

### 31.9 Migration strategy

Prefer expand-and-contract. Destructive migrations require explicit backup, restore test, impact report, minimum compatible version, warning, and approval.

Embeddings and indexes are rebuildable. Raw evidence, claims, approvals, and report lineage are not treated as disposable.

## 32. Backup, recovery, and lifecycle

### 32.1 Backup products

#### Research bundle

Subject/project-scoped evidence, source artifacts, claims, calculations, reports, approvals, cutoffs, selected snapshots, and manifest.

#### Workspace backup

Database logical snapshot, artifact manifests, required files, Parquet manifests, configuration, prompts/schemas, analyst decisions, and evaluation datasets.

#### Disaster-recovery backup

Consistent database, recovery metadata, artifact store, Parquet, encryption metadata, compatibility manifest, and optional model artifacts.

### 32.2 Backup barrier

```text
finish active transactions
→ flush publication outbox
→ record database snapshot point
→ freeze artifact manifest
→ freeze Parquet manifest
→ copy
→ verify hashes
→ sign backup manifest
→ release barrier
```

### 32.3 Encryption and verification

Backups use a random data key wrapped by a Keychain recovery key and optional portable passphrase.

Success requires signature, hashes, database readability, artifact count, schema compatibility, decryption, sample evidence traversal, and sample report reproduction.

### 32.4 Recovery hierarchy

```text
1 restart worker and resume checkpoint
2 restart service and replay outbox
3 rebuild derived indexes/features
4 replay raw envelopes
5 restore database backup
6 restore complete workspace on fresh installation
```

### 32.5 Integrity scrubbing

Periodic checks cover raw/canonical/report/model/runtime hashes, Parquet manifests, database integrity, citation resolution, and orphaned/missing filesystem/database objects.

### 32.6 First launch

```text
verify signatures/manifests
→ choose Offline or Monitored
→ initialize directories and Keychain
→ initialize PostgreSQL
→ migrate
→ register user service
→ select hardware policy
→ import/register models
→ detect optional Bitcoin Core and Codex
→ create workspace
→ run diagnostics
→ open Command Center
```

### 32.7 Startup and shutdown

Startup verifies runtime, data root, database, migrations, sockets, models, disk, memory, and interrupted runs. The UI opens in diagnostic mode even if the engine is degraded.

Shutdown stops new work, checkpoints graphs, finishes publication, flushes trace metadata, closes clients, stops workers, unloads models, and preserves configured monitoring.

### 32.8 Safe Mode

Safe Mode disables collectors, models, parser workers, automatic migration, and workflow resumption. It provides read-only access where possible, export, backup, integrity verification, rollback, disable/rebuild controls, and support-bundle generation.

### 32.9 `atlas doctor`

Checks signatures, entitlements, manifests, Python imports, database, pgvector, permissions, sockets, workers, model hashes, Bitcoin Core, collectors, telemetry, Codex contract, backups, and zero-egress.

Statuses:

```text
healthy
degraded
blocked
unsafe
repairable
```

### 32.10 Uninstallation

Removing the app does not delete research data. Application removal, runtime removal, and secure workspace destruction are separate explicit actions.

A reinstall can reattach an existing workspace after compatibility and integrity checks.

### 32.11 Vulnerability and research-correction response

Security and research-integrity incidents follow validation, affected-version analysis, regression test, isolated patch, complete suites, signed release, advisory, credential/key rotation where needed, downstream impact analysis, corrected report versions, preserved history, and post-incident review.
## 33. Acceptance criteria

The following criteria are normative for the first complete production-grade portfolio release.

### 33.1 Product and UX

1. Native SwiftUI application launches and controls the full local runtime.
2. Analyst, Advanced, and Engineering visibility presets are available.
3. Command Center reports workflows, source health, freshness, models, resources, alerts, and regressions.
4. Protocol/asset workspaces contain documents, tokenomics, security, governance, treasury, development, chain, market, claims, contradictions, alerts, and research.
5. Research Canvas exposes plan, live graph, evidence, calculations, conflicts, notes, and approvals.
6. Evidence Inspector resolves every citation to a source region or structured observation.
7. Report Studio preserves citation lineage through analyst edits and reruns affected validators.
8. Parser, Chunking, Retrieval, Data/Feature, Evaluation, Trace/Agent, and Codex laboratories are usable from the native app.
9. Keyboard navigation, VoiceOver, Reduce Motion, light/dark mode, and multi-window behavior pass acceptance tests.

### 33.2 Ingestion

10. Exact duplicate and new-version handling work.
11. Born-digital and scanned PDFs work.
12. Parser fallback is based on measured quality.
13. Canonical page/layout provenance is preserved.
14. At least five chunking families are implemented; the framework supports the full strategy registry.
15. Parent-child and table-aware chunking are production-ready.
16. Local dense and lexical indexing work.
17. Every external and model boundary uses strict schema validation.
18. Publication is atomic and rollbackable.
19. Deliberate worker termination resumes without losing completed immutable outputs.
20. Human interrupt and later resumption work.
21. Page-level citation reconstruction works.
22. Parser and chunker benchmarks exist.
23. Reprocessing never overwrites historical lineage.
24. Strict offline ingestion completes without network access.

### 33.3 Retrieval

25. Exact EVM, Solana, and Bitcoin identifier lookup works.
26. Ambiguous identity is visible and blocks material queries where unresolved.
27. Historical as-of retrieval is reproducible.
28. Dense, lexical, exact, structured, edge, time-series, and chain-snapshot retrieval operate.
29. Intent routes across data planes.
30. Parent, table, figure, definition, and footnote expansion work.
31. Fusion component ranks are inspectable.
32. Local cross-encoder reranking works.
33. Optional LLM reranking is constrained and evaluated.
34. Coverage matrix and contradiction probes run.
35. Repair loops are bounded.
36. Insufficient evidence produces honest abstention.
37. Prompt-injection source content cannot gain tool authority.
38. Retrieval works in degraded mode without vector or large-model services.
39. Frozen-snapshot exact and comparative replay work.
40. Regression gates prevent harmful promotion.

### 33.4 Research, agents, and reports

41. Typed investigation plans are deterministically validated.
42. Specialists execute in isolated contexts with strict tools.
43. Due diligence works for an EVM protocol, a Solana protocol, and Bitcoin.
44. A normalized cross-ecosystem comparison works.
45. Monitoring can start targeted material-change research.
46. Copilot routes quick questions versus full investigation.
47. Specialist inputs/outputs are schema validated.
48. Findings include support, contradiction, uncertainty, and missing evidence.
49. Deterministic calculations are separate from interpretation.
50. Assertions are constructed before prose.
51. Report writing cannot silently introduce material unsupported claims.
52. Citations bind before rendering.
53. Document, chain, market, code, and calculation citations resolve.
54. Every material displayed number revalidates.
55. Local judges run and are calibrated against human labels.
56. Pairwise tests randomize order.
57. Repair is targeted and capped.
58. Review decisions are immutable.
59. Report edits trigger dependent validation.
60. Every published sentence has complete lineage.

### 33.5 Structured data and monitoring

61. Offline bundle import and monitored collection share downstream contracts.
62. Every payload has an immutable raw envelope.
63. Collector cursor, lease, idempotency, retry, rate limit, and circuit breaker work.
64. Bitcoin Core collection and reorganization handling work.
65. EVM block/log/receipt/state/bytecode evidence and reorganization handling work.
66. Solana block/transaction/instruction/account/program evidence and commitment handling work.
67. Raw and decoded chain representations coexist.
68. Provider disagreement is explicit.
69. Market snapshot/delta reconciliation and gap resnapshot work.
70. Financial precision is exact.
71. Venue and instrument identity are normalized.
72. DEX records link back to chain evidence.
73. Protocol metrics expose methodology.
74. On-chain and off-chain governance link.
75. GitHub collection is cursor and rate-limit aware.
76. Observation storage is bitemporal and point-in-time correct.
77. Data-quality failures quarantine rather than disappear.
78. Raw replay rebuilds corrected normalized observations.
79. Parquet manifests and DuckDB analytics work.
80. Feature definitions, dependencies, versions, and leakage tests work.
81. Research signals cannot trade.
82. Monitoring performs deterministic detection before semantic triage.
83. Alerts deduplicate, progress through lifecycle, and link affected research.
84. Every feature and alert navigates to raw evidence.

### 33.6 Models, evaluation, and observability

85. Model providers are interchangeable behind one interface.
86. Apple Foundation Models work for approved tasks and fall back safely.
87. A relevant Apple model/OS change triggers regression qualification.
88. Local reasoning, embedding, reranking, and vision services are isolated.
89. Models load and unload without restarting the engine.
90. One-heavy-model-at-a-time scheduling works.
91. Model-worker kill and OOM recovery work.
92. Model and tokenizer artifacts are immutable, licensed, hashed, and evaluated.
93. Prompt/model compatibility is explicit.
94. Evaluation datasets include development, calibration, regression, adversarial, holdout, and shadow slices.
95. Code evaluators precede model judges.
96. Judge false acceptance, false rejection, stability, and bias are measured.
97. Experiments compare paired configurations with confidence intervals and critical-slice gates.
98. Production failures become regression examples.
99. Traces span Swift, Python, LangGraph, workers, models, collectors, and Codex.
100. Payload privacy modes and local retention work.
101. No hidden reasoning is required for reproducibility.
102. LangSmith-compatible attributes can be emitted while all exporters remain disabled in strict mode.

### 33.7 Codex

103. Codex operates only in the engineering plane.
104. The selected Codex version and local provider pass contract tests.
105. Interactive and automated event streams are inspectable.
106. Codex runs in an isolated worktree.
107. Production credentials and private research remain inaccessible.
108. Network is denied in strict mode.
109. Commands and file changes follow approval policy.
110. Codex cannot merge, push, deploy, publish research, or promote evaluations automatically.
111. Patches pass the complete software and AI quality gate.

### 33.8 Security, packaging, and recovery

112. The complete app and nested code are signed and notarized.
113. Runtime entitlements match the reviewed process capability matrix.
114. No production TCP API exists.
115. Offline distribution performs no external network access.
116. Monitored mode permits only allowlisted collectors and update destinations.
117. Secrets remain in Keychain and out of prompts, traces, and bundles.
118. Parser and model workers are network disabled.
119. Untrusted document and archive containment tests pass.
120. Models cannot submit arbitrary SQL or shell commands.
121. Dependencies, models, and tokenizers are hash pinned.
122. Every release has an SBOM and signed manifest.
123. The Python runtime is embedded and isolated.
124. Runtime pip and arbitrary plugins are absent.
125. PostgreSQL and pgvector are local-socket only.
126. No root daemon or privileged helper is required.
127. Clean installation, upgrade, rollback, migration, backup, restore, and safe-mode tests pass.
128. Derived indexes and features rebuild from durable evidence.
129. Structured observations rebuild from raw envelopes.
130. Integrity scrub detects missing or modified artifacts.
131. `atlas doctor` produces actionable health states.
132. Application removal and data deletion are separate.
133. Vulnerability and research-correction procedures preserve history and affected-report lineage.
134. No trading, wallet, signing, or private-key capability exists.

## 34. Delivery decomposition

The architecture is intentionally broad; implementation shall proceed as independently demonstrable vertical slices.

### Phase 1 — Foundation and local runtime

- Monorepo structure.
- SwiftUI shell and service lifecycle.
- Python engine, schemas, PostgreSQL, artifact store, OpenTelemetry.
- Offline profile and resource supervisor.
- Basic model registry and local provider abstraction.

### Phase 2 — Document intelligence

- Secure import, admission, parser portfolio, canonical model.
- Parser and chunking laboratories.
- Dense/lexical index.
- Page-level evidence inspector.
- Ingestion evaluation and atomic publication.

### Phase 3 — Retrieval and research

- Entity resolution and frozen cutoffs.
- Hybrid retrieval, fusion, reranking, coverage, repair, and replay.
- Due-diligence graph.
- Assertion and citation model.
- Report Studio and validation.

### Phase 4 — Multi-chain and quantitative data

- Bitcoin Core.
- Generic EVM RPC.
- Generic Solana RPC.
- One market connector.
- GitHub and governance connectors.
- Observation model, quality contracts, Parquet/DuckDB, feature registry.

### Phase 5 — Monitoring and comparison

- Change detection.
- Dependency invalidation.
- Alert lifecycle.
- Cross-protocol comparison.
- Cross-chain timeline.

### Phase 6 — Engineering and release maturity

- Full evaluation center.
- Judge calibration.
- Codex engineering integration.
- Fault and adversarial suites.
- Packaging, signing, notarization, update, backup, recovery, and clean-machine qualification.

Each phase must end in an end-to-end vertical demonstration and preserve the contracts needed by later phases.

## 35. Selection-by-evaluation decisions

The following are intentionally not hard-coded product decisions. They are controlled experiment choices with explicit promotion criteria:

- Primary structure-aware PDF parser and fallback order.
- OCR engine.
- Local VLM.
- Production embedding model.
- Cross-encoder reranker.
- Primary and judge reasoning models.
- MLX versus OpenAI-compatible runtime by task.
- Exact chunk sizes and semantic thresholds.
- Fusion weights and candidate counts.
- First EVM network beyond Ethereum.
- First spot and derivatives market providers.
- First protocol-specific adapters.
- Optional local BM25/Tantivy backend.
- Exact encrypted-artifact policy by workspace class.

For each, RSI Atlas shall compare quality, critical errors, latency, memory, disk, stability, licensing, and reproducibility on frozen benchmarks. The chosen configuration is then stored as a versioned production policy with rollback.

## 36. Principal risks and mitigations

| Risk | Mitigation |
|---|---|
| Scope becomes too broad | Vertical slices, watchlist-scoped connectors, production adapters only after complete quality contracts |
| Local memory exhaustion | Resource arbiter, on-demand workers, one heavy model at a time, smaller fallbacks, benchmarked context limits |
| LLM fluency hides unsupported conclusions | Assertion-first synthesis, evidence binding, deterministic gates, citation judges, analyst review |
| Parser diversity creates operational complexity | Common canonical schema, sandboxed candidates, measured parser plan, limited production policy |
| Multi-chain normalization becomes misleading | Shared provenance header plus chain-native payloads and adapters |
| Historical research leaks future information | `available_time`, frozen cutoffs, point-in-time joins, temporal regression tests |
| Local Codex/provider compatibility changes | Pin and qualify Codex/provider pairs, contract tests, optional integration, manual fallback |
| Apple on-device model changes with OS updates | Record OS/model environment, invalidate prompt qualification, rerun regressions, fallback |
| Continuous monitoring overwhelms workstation | Tiered cadence, resource classes, reserved critical capacity, bounded backfills |
| Self-hosted observability becomes too heavy | Compact local telemetry model; no self-hosted LangSmith dependency |
| Security claim exceeds actual process isolation | Release-level socket tests, egress tests, entitlement audit, explicit host-account trust boundary |
| Reports become unreproducible after source updates | Immutable source versions, frozen manifests, bitemporal history, exact and comparative replay |

## 37. Normative technology references

Implementation shall use primary documentation, pin exact dependency and model artifacts, and re-verify behavior during planning and every upgrade. The dated reference set used to validate this specification is retained in Appendix F. A reference documents an available mechanism; it is not a guarantee that every future upstream version remains compatible.


## Appendix A. Recommended monorepo layout

```text
rsi-atlas/
├── apps/
│   └── macos/                       SwiftUI Workstation and Studio
├── services/
│   ├── engine/                      local API and application services
│   ├── modeld/                      reasoning-model daemon
│   ├── foundation-bridge/           native Foundation Models provider
│   ├── workers/                     document, model, data, and evaluation workers
│   ├── collectors/                  monitored and local-node collectors
│   └── codex-controller/            isolated engineering integration
├── packages/
│   ├── domain/                      identities, evidence, claims, reports
│   ├── contracts/                   versioned Pydantic and generated Swift models
│   ├── workflows/                   LangGraph graphs and subgraphs
│   ├── ingestion/                   acquisition, parsing, canonicalization
│   ├── chunking/                    strategies and experiments
│   ├── retrieval/                   planning, fusion, reranking, context
│   ├── research/                    specialists, assertions, synthesis
│   ├── chains/                      EVM, Solana, and Bitcoin
│   ├── markets/                     venue and instrument normalization
│   ├── governance/                  governance evidence
│   ├── development/                 GitHub and code evidence
│   ├── features/                    point-in-time feature registry and DAG
│   ├── monitoring/                  changes, rules, alerts
│   ├── models/                      routing, artifacts, prompts
│   ├── evaluation/                  datasets, judges, experiments
│   ├── observability/               traces, metrics, redaction
│   ├── security/                    policy and capabilities
│   └── storage/                     PostgreSQL, artifact, and Parquet adapters
├── migrations/
├── tests/
│   ├── unit/
│   ├── property/
│   ├── contract/
│   ├── golden/
│   ├── integration/
│   ├── security/
│   ├── fault/
│   └── evaluation/
├── datasets/
│   ├── public-fixtures/
│   └── manifests/
├── infra/
│   ├── local/
│   ├── signing/
│   ├── release/
│   └── telemetry/
├── scripts/
└── docs/
```

Dependency direction is inward: domain and contracts know no UI, database, LangChain, LangGraph, model-runtime, or transport framework. Application services depend on domain contracts; workflows and infrastructure adapters depend on application services. LangGraph nodes remain thin orchestration wrappers around independently tested services.

## Appendix B. Reference demonstration scenarios

The public portfolio demonstration shall use replaceable source manifests and include:

1. One EVM protocol dossier with documents, audits, governance, contracts, markets, and development evidence.
2. One Solana protocol dossier with documents, tokenomics, program/account evidence, markets, governance, and development evidence.
3. One Bitcoin network/asset dossier using the local node, public research documents, development releases, and market/network metrics.
4. A protocol comparison using only explicitly comparable dimensions and displaying missing or non-comparable fields.
5. A material document-version change and downstream report invalidation.
6. An EVM upgrade or administrative-control event.
7. A Solana program or authority change.
8. A Bitcoin reorganization simulation.
9. A market sequence gap and deterministic resnapshot.
10. A malicious prompt-injection document that cannot alter tools or policy.
11. A parser disagreement requiring human review and later LangGraph resumption.
12. A chunker, embedding, retriever, or reranker experiment against a frozen benchmark.
13. A judge disagreement resolved through deterministic results and human annotation.
14. A report correction after changed evidence while preserving the original publication.
15. A sanitized failure bundle passed to local Codex, followed by a reviewable patch and full regression gate.

Reference subjects are selected through public fixture manifests during implementation rather than hard-coded into product logic. The fixture set must remain redistributable under its source licenses.

## Appendix C. Approved decision log

| ID | Decision | Rationale |
|---|---|---|
| D-001 | Product domain is crypto research and due diligence. | Produces domain-specific schemas, meaningful evaluation, and a strong quantitative portfolio story. |
| D-002 | Support due diligence, comparison, monitoring, and copilot in one platform. | These workflows share the same evidence, identity, retrieval, and validation foundations. |
| D-003 | Solo researcher first; small fund team ready. | Keeps local operation practical while preserving review, roles, and audit boundaries. |
| D-004 | Greenfield monorepo. | Enables clean domain boundaries and cross-language contracts. |
| D-005 | Fully local on 24–36 GB Apple Silicon. | Privacy, portfolio differentiation, and explicit resource engineering. |
| D-006 | Strict zero egress with air-gapped and monitored profiles. | Separates research privacy from controlled public-source acquisition. |
| D-007 | Full research data architecture, implemented through deep vertical slices. | Avoids a document-only demo without attempting shallow global connector coverage. |
| D-008 | Bitcoin, EVM, and Solana from the first complete product release. | Demonstrates chain abstraction without erasing native semantics. |
| D-009 | Hybrid chain access: local Bitcoin Core, allowlisted EVM/Solana providers, immutable snapshots. | Practical on the target workstation while preserving reproducibility. |
| D-010 | Native SwiftUI analyst workstation. | Best macOS integration, evidence inspection, charts, file access, Foundation Models, and portfolio value. |
| D-011 | Include a full Engineering Studio. | Makes parser, chunker, retriever, agent, evaluation, data, and resource behavior visible. |
| D-012 | Hybrid native-professional and selective futuristic visual language. | Preserves density and usability while making intelligent-system states legible. |
| D-013 | Product name is RSI Atlas under Research Signal Intelligence. | Institutional product identity with extensible module naming. |
| D-014 | Modular monolith with isolated workers. | Balances clear architecture, fault isolation, and local operational efficiency. |
| D-015 | Evidence graph and relational source of truth; vector search is a retrieval mechanism. | Prevents embeddings or chat history from becoming the durable truth model. |
| D-016 | Structure-aware parent-child chunking is the initial production policy. | Strong default for long structured documents while remaining benchmark-driven. |
| D-017 | Hybrid retrieval with dense, lexical, exact, structured, graph, and time-series planes. | Crypto questions mix conceptual, exact, numeric, temporal, and identifier-heavy evidence. |
| D-018 | Deterministic outer workflows with bounded agents. | Agents are used only for semantic judgment and cannot bypass policy or publication gates. |
| D-019 | Apple Foundation Models for light local tasks; larger local models for complex reasoning. | Cascaded local inference improves latency and resource use. |
| D-020 | Codex is an engineering tool, not a production research agent. | Prevents software-editing authority from entering live investment research. |
| D-021 | Local OpenTelemetry and evaluation are primary; LangSmith is optional compatibility. | Meets zero-egress and hardware constraints while retaining industry-standard concepts. |
| D-022 | No trading, wallet, or signing capability. | Keeps the platform research-only and materially reduces operational risk. |
| D-023 | Signed/notarized native distribution with embedded isolated Python. | Provides a professional macOS product without system-Python or container dependence. |

---

## Appendix D. System-wide verification matrix

| Capability | Required evidence of completion |
|---|---|
| Immutable evidence | Hash-verified raw artifacts and raw envelopes; version/supersession history; integrity scrub report. |
| Durable workflow | Deliberate worker/process termination followed by checkpointed recovery without duplicate publication. |
| PDF intelligence | Born-digital and scanned fixtures; parser fallback; exact PDF-region citation; parser comparison. |
| Chunking | At least five implemented families; parent-child and table-aware production policy; labelled benchmark. |
| Retrieval | Dense, lexical, exact, structured, graph, and time-series traces; fusion/rerank scores; abstention case. |
| Multi-agent research | Typed plan, isolated specialists, strict tool policy, human interrupt/resume, targeted repair. |
| Numerical integrity | Deterministic calculation manifests; report value revalidation; unit and point-in-time tests. |
| Citation integrity | Material-claim coverage, exact locators, semantic entailment, contradiction disclosure. |
| Multi-chain | Reproducible EVM, Solana, and Bitcoin snapshots; finality/commitment/reorg tests. |
| Market data | REST snapshot and WebSocket sequence reconciliation; fixed precision; gap recovery. |
| Monitoring | Deterministic change, materiality, targeted investigation, dependency invalidation, deduplicated alert. |
| Local models | Capability registry, model hashes/licenses, memory qualification, crash/OOM recovery, fallback. |
| Evaluation | Versioned datasets, human calibration, code + judge metrics, statistical baseline comparison. |
| Observability | Distributed trace from Swift action to publication; privacy mode and local retention demonstration. |
| Native application | Analyst and Engineering presets, evidence overlay, report editing, graph timeline, accessibility. |
| Zero egress | Recorded network-denial acceptance test for the exact release artifact. |
| Codex | Local-only provider, Unix-socket protocol, isolated worktree, sanitized fixture, explicit approval, gated patch. |
| Security | Signed peers, sandbox/entitlement evidence, secret-redaction tests, malicious-document containment. |
| Release | SBOM, signed manifest, notarization, Gatekeeper, clean install, upgrade, rollback. |
| Recovery | Encrypted backup, verified fresh-install restore, index rebuild, raw-envelope replay, Safe Mode. |

---

## Appendix E. Implementation-plan inputs

The implementation plan must turn this design into small, test-driven vertical tasks. It must explicitly include:

1. File paths and package boundaries for each task.
2. A failing test or evaluation case before implementation where practical.
3. Exact local commands for verification.
4. Checkpoints after every vertical slice.
5. Reference fixtures and expected outputs.
6. Resource budgets for model and parser tasks.
7. Migration and rollback steps for durable state changes.
8. Security and zero-egress verification for every component that can open files, sockets, or subprocesses.
9. A dependency graph that prevents UI work from outrunning stable domain and contract foundations.
10. A release of usable capability at the end of each milestone rather than a long infrastructure-only phase.

### E.1 Benchmark-selected implementation choices

The architecture intentionally does not hard-code volatile model or provider names. The implementation plan must select exact artifacts using the approved benchmark process.

| Choice | Initial candidate/default | Selection rule |
|---|---|---|
| Structure-aware PDF parser | Docling | Promote only after crypto PDF golden and resource tests. |
| OCR fallback | Local OCR through parser portfolio | Select page/document policies by quality and latency. |
| Vector store | PostgreSQL + pgvector | Replace only if measured workload justifies another backend. |
| Lexical search | PostgreSQL full-text | Add Tantivy adapter only after benchmark. |
| Reasoning runtime | MLX-capable isolated daemon | Ollama remains independent compatibility fallback. |
| Light semantic model | Apple Foundation Models where available | Require OS-version regression and task qualification. |
| Embedding model | Local model selected by retrieval benchmark | Must fit memory, license, multilingual, and quality policies. |
| Reranker | Local cross-encoder | Must produce measurable nDCG/MRR gain within latency budget. |
| Coding model | Locally approved Codex-compatible model | Must pass tool/patch/test and sandbox benchmarks. |
| Reference protocols | Public EVM and Solana protocols plus Bitcoin | Select for stable primary sources, audit/governance data, and legal fixture use. |

These are governed choices, not unresolved placeholders.

---

## Appendix F. Primary technical references

The design decisions above were checked against the following primary documentation available on 2026-07-18. Implementation must pin actual dependency versions and re-verify behavior during planning and upgrades.

### Apple platform and local intelligence

1. [Apple Foundation Models](https://developer.apple.com/documentation/foundationmodels/)
2. [Foundation Models updates](https://developer.apple.com/documentation/updates/foundationmodels)
3. [SystemLanguageModel availability](https://developer.apple.com/documentation/foundationmodels/systemlanguagemodel)
4. [Foundation Models tool calling](https://developer.apple.com/documentation/foundationmodels/expanding-generation-with-tool-calling)
5. [Protecting user data with App Sandbox](https://developer.apple.com/documentation/security/protecting-user-data-with-app-sandbox)
6. [SMAppService registration](https://developer.apple.com/documentation/servicemanagement/smappservice/register%28%29)
7. [XPC peer team identity requirement](https://developer.apple.com/documentation/xpc/xpc_connection_set_peer_team_identity_requirement%28_%3A_%3A%29)
8. [Resolving common notarization issues](https://developer.apple.com/documentation/security/resolving-common-notarization-issues)
9. [Customizing the notarization workflow](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow)

### LangChain, LangGraph, and LangSmith

10. [LangGraph workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
11. [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
12. [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
13. [LangGraph subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)
14. [LangChain structured output](https://docs.langchain.com/oss/python/langchain/structured-output)
15. [LangChain retrieval architectures](https://docs.langchain.com/oss/python/langchain/retrieval)
16. [LangChain document loaders](https://docs.langchain.com/oss/python/integrations/document_loaders)
17. [LangChain Docling integration](https://docs.langchain.com/oss/python/integrations/document_loaders/docling)
18. [LangSmith evaluation concepts](https://docs.langchain.com/langsmith/evaluation-concepts)
19. [LangSmith evaluation lifecycle](https://docs.langchain.com/langsmith/evaluation)
20. [LangSmith OpenTelemetry tracing](https://docs.langchain.com/langsmith/trace-with-opentelemetry)
21. [LangSmith self-hosting](https://docs.langchain.com/langsmith/self-hosted)

### Parsing, storage, and observability

22. [Unstructured partitioning](https://docs.unstructured.io/open-source/core-functionality/partitioning)
23. [pgvector](https://github.com/pgvector/pgvector)
24. [DuckDB querying Parquet](https://duckdb.org/docs/stable/data/parquet/overview)
25. [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/)
26. [Sparkle documentation](https://sparkle-project.org/documentation/)
27. [Embedding Python](https://docs.python.org/3/extending/embedding.html)

### Local model and Codex engineering plane

28. [MLX](https://github.com/ml-explore/mlx)
29. [MLX-LM](https://github.com/ml-explore/mlx-lm)
30. [Ollama OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
31. [Codex App Server](https://developers.openai.com/codex/app-server/)
32. [Codex advanced configuration and local providers](https://developers.openai.com/codex/config-advanced/)
33. [Codex non-interactive mode](https://developers.openai.com/codex/non-interactive-mode/)

### Chain, market, and development sources

34. [Ethereum JSON-RPC](https://ethereum.org/en/developers/docs/apis/json-rpc/)
35. [Solana RPC methods](https://solana.com/docs/rpc)
36. [Bitcoin Core RPC reference](https://developer.bitcoin.org/reference/rpc/)
37. [Bitcoin Core ZMQ interface](https://github.com/bitcoin/bitcoin/blob/master/doc/zmq.md)
38. [Binance Spot API documentation](https://developers.binance.com/docs/binance-spot-api-docs)
39. [GitHub REST API rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)

---

## Appendix G. Approval state

All product and architecture sections in this specification were approved during the design dialogue. This document is the implementation-planning baseline. Any material change to the following requires a new architecture decision record and user approval:

```text
local-first and zero-egress posture
supported chain families
native macOS primary interface
evidence and lineage invariants
deterministic calculation authority
bounded-agent model
human-review and publication gates
research-only/no-trading boundary
Codex engineering-only boundary
release security posture
```

The next process step is to create the detailed implementation plan from this specification.

---

## 38. Specification conclusion

RSI Atlas is a local-first crypto intelligence operating system built around evidence, reproducibility, and inspection.

Its defining architecture is:

```text
untrusted sources
→ immutable artifacts and observations
→ canonical document and chain-native models
→ evaluated chunking and feature policies
→ hybrid retrieval
→ bounded specialist research
→ deterministic calculations
→ assertion-first synthesis
→ exact citations
→ deterministic and semantic validation
→ analyst review
→ reproducible reports, comparisons, alerts, and signals
```

The platform demonstrates complete LLM-system engineering rather than a narrow chatbot implementation:

- PDF parsing and OCR.
- Multiple chunking approaches and measurable selection.
- Embeddings and vector search.
- Hybrid retrieval and reranking.
- LangChain integrations.
- LangGraph durable workflows and multi-agent patterns.
- Local LangSmith-compatible evaluation and observability concepts.
- Pydantic validation.
- LLM-as-judge with human calibration.
- Multi-chain, market, governance, protocol, and development data.
- Quantitative features and point-in-time correctness.
- Native macOS product design.
- Apple Foundation Models.
- Local model routing.
- Controlled Codex engineering.
- Security, testing, packaging, update, backup, and recovery.

The design intentionally keeps deterministic truth, model inference, and analyst judgment separate while allowing them to cooperate through versioned contracts. That separation is the central production property of RSI Atlas.
