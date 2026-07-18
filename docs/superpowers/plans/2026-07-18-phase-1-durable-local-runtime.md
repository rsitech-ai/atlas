# Phase 1 Durable Local Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the remaining Phase 1 substrate so RSI Atlas has immutable local artifacts, PostgreSQL/pgvector persistence, enforced runtime policy, local OpenTelemetry traces, resource/model boundaries, and a Command Center driven by real probes rather than constants.

**Architecture:** Keep domain contracts independent of persistence and transport. A content-addressed filesystem owns immutable bytes; PostgreSQL owns durable metadata and active state through explicit migrations and Unix-socket-only connections; policy, observability, resource, and model packages expose deterministic interfaces consumed by the engine. Swift continues to consume versioned status contracts and renders actionable native state without becoming a research-logic layer.

**Tech Stack:** Python 3.11+, Pydantic 2.13.4, Psycopg 3.3.4, PostgreSQL 17.10 with pgvector 0.8.5 for the development integration runtime, OpenTelemetry API/SDK 1.44.0, FastAPI 0.139.2, Swift 6.3 / SwiftUI / Swift Testing, uv 0.5.x, raw versioned SQL migrations.

## Global Constraints

- Primary platform: Apple Silicon macOS, 24–36 GB unified memory.
- Default privacy posture: strict zero egress for private data, prompts, model inputs, embeddings, traces, reports, and evaluations.
- Raw artifacts never mutate; changed bytes create a new content hash and later version relation.
- Tenant, workspace, and actor identifiers are mandatory in durable commands, records, and traces.
- Hashing, validation, persistence, permissions, state transitions, and source-of-truth writes are deterministic.
- No production listener binds to a LAN interface; PostgreSQL uses a local Unix socket only.
- Development loopback HTTP remains explicitly development-only; it is not release IPC evidence.
- Secrets never enter environment files, graph state, prompts, traces, raw envelopes, Codex bundles, or ordinary exports.
- The system has no trade, wallet, blockchain-signing, exchange-account, or private-key capability.
- Every new behavior follows RED → GREEN → REFACTOR and receives task-scoped specification and quality review before the next writer task.
- No parser, OCR, VLM, embedding, reranker, reasoning model, judge, collector provider, or protocol adapter is promoted in Phase 1.

---

### Task 1: Immutable content-addressed artifact store

**Files:**
- Create: `packages/contracts/src/rsi_atlas_contracts/artifact.py`
- Modify: `packages/contracts/src/rsi_atlas_contracts/__init__.py`
- Create: `packages/storage/pyproject.toml`
- Create: `packages/storage/src/rsi_atlas_storage/__init__.py`
- Create: `packages/storage/src/rsi_atlas_storage/artifact_store.py`
- Create: `packages/storage/tests/test_artifact_store.py`
- Modify: `pyproject.toml`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `ArtifactID`, `ArtifactDescriptor`, `ArtifactIntegrityError`, and `ContentAddressedArtifactStore`.
- `ContentAddressedArtifactStore.put_bytes(payload: bytes, *, media_type: str, context: ArtifactCommandContext) -> ArtifactDescriptor` computes SHA-256, writes atomically through no-follow directory descriptors, and is idempotent for identical bytes.
- `ContentAddressedArtifactStore.read_bytes(artifact_id: ArtifactID, *, context: ArtifactCommandContext) -> bytes` re-hashes content before returning it.
- `ContentAddressedArtifactStore.verify(artifact_id: ArtifactID, *, context: ArtifactCommandContext) -> ArtifactDescriptor` fails closed on missing or modified bytes/manifest.
- Later tasks persist only the returned descriptor; database metadata never becomes proof that bytes exist.

- [x] **Step 1: Write failing immutable-store tests**

```python
def test_identical_bytes_reuse_one_artifact(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path)
    first = store.put_bytes(b"atlas evidence", media_type="application/octet-stream")
    second = store.put_bytes(b"atlas evidence", media_type="application/octet-stream")
    assert first == second
    assert first.artifact_id == f"sha256:{hashlib.sha256(b'atlas evidence').hexdigest()}"
    assert len(tuple(tmp_path.rglob("payload"))) == 1


def test_changed_bytes_create_a_distinct_artifact(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path)
    first = store.put_bytes(b"version one", media_type="application/pdf")
    second = store.put_bytes(b"version two", media_type="application/pdf")
    assert first.artifact_id != second.artifact_id


def test_read_rejects_modified_content(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path)
    artifact = store.put_bytes(b"trusted", media_type="application/pdf")
    store.payload_path(artifact.artifact_id).write_bytes(b"tampered")
    with pytest.raises(ArtifactIntegrityError, match="content hash mismatch"):
        store.read_bytes(artifact.artifact_id)


def test_invalid_artifact_identifier_cannot_escape_root(tmp_path: Path) -> None:
    store = ContentAddressedArtifactStore(tmp_path)
    with pytest.raises(ValueError, match="artifact identifier"):
        store.read_bytes(cast(ArtifactID, "sha256:../../outside"))
```

- [x] **Step 2: Run the focused test and verify RED**

Run: `uv run pytest packages/storage/tests/test_artifact_store.py -q`

Expected: collection fails because `rsi_atlas_storage` and the artifact contracts do not exist.

- [x] **Step 3: Implement the strict descriptor and atomic store**

```python
class ArtifactDescriptor(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    artifact_id: ArtifactID
    algorithm: Literal["sha256"] = "sha256"
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str = Field(min_length=1)


class ContentAddressedArtifactStore:
    def put_bytes(self, payload: bytes, *, media_type: str) -> ArtifactDescriptor:
        digest = hashlib.sha256(payload).hexdigest()
        descriptor = ArtifactDescriptor(
            artifact_id=f"sha256:{digest}",
            digest=digest,
            size_bytes=len(payload),
            media_type=media_type,
        )
        directory = self._directory_for(descriptor.artifact_id)
        directory.mkdir(parents=True, exist_ok=True)
        self._publish_once(directory / "payload", payload)
        self._publish_once(
            directory / "manifest.json",
            descriptor.model_dump_json(indent=2).encode("utf-8"),
        )
        return self.verify(descriptor.artifact_id)
```

`_publish_once` writes to a unique file in the destination directory, flushes and `fsync`s it, links or replaces only when the destination does not exist, verifies an existing destination rather than overwriting it, and removes the staging file in `finally`. Artifact paths are derived only from a validated 64-character lowercase hexadecimal digest under `sha256/<first-two>/<next-two>/<digest>/`.

- [x] **Step 4: Run focused and boundary verification**

Run:

```bash
uv run pytest packages/storage/tests/test_artifact_store.py -q
uv run ruff check packages/contracts packages/storage
uv run mypy packages/contracts/src packages/storage/src
```

Expected: artifact tests pass; static checks are clean; a deliberate content mutation raises `ArtifactIntegrityError`.

- [x] **Step 5: Commit and review Task 1**

```bash
git add .gitignore pyproject.toml uv.lock packages/contracts packages/storage
git commit -m "feat: add immutable artifact store"
```

Generate the task review package from the pre-task base to the task head. Do not start Task 2 until specification compliance and code quality are both approved and all Critical/Important findings are resolved.

### Task 2: Unix-socket PostgreSQL and pgvector persistence

**Files:**
- Modify: `packages/storage/pyproject.toml`
- Create: `packages/storage/src/rsi_atlas_storage/database.py`
- Create: `packages/storage/src/rsi_atlas_storage/migrations.py`
- Create: `packages/storage/src/rsi_atlas_storage/artifact_repository.py`
- Create: `packages/storage/tests/test_database_policy.py`
- Create: `packages/storage/tests/test_postgres_integration.py`
- Create: `migrations/0001_foundation.sql`
- Create: `infra/local/postgres.sh`
- Modify: `pyproject.toml`
- Modify: `script/build_and_run.sh`
- Modify: `README.md`

**Interfaces:**
- Consumes: `ArtifactDescriptor` and the verified filesystem artifact from Task 1.
- Produces: `DatabaseSettings`, `PostgresDatabase`, `MigrationRunner`, `ArtifactRepository`, and schema version `0001`.
- `DatabaseSettings.from_conninfo()` rejects TCP hosts, missing database/user, and non-owner socket roots.
- `ArtifactRepository.register()` commits metadata only after `ContentAddressedArtifactStore.verify()` succeeds.
- Development PostgreSQL is initialized under the injected `RSI_ATLAS_DATA_ROOT`; release data placement remains outside the app bundle and is a later packaging gate.

- [x] **Step 1: Write failing policy and integration tests**

```python
def test_database_settings_reject_tcp_host() -> None:
    with pytest.raises(ValueError, match="Unix socket"):
        DatabaseSettings.from_conninfo("postgresql://atlas@127.0.0.1/atlas")


def test_migrations_enable_vector_and_are_idempotent(postgres_database: PostgresDatabase) -> None:
    runner = MigrationRunner(postgres_database, Path("migrations"))
    runner.apply_all()
    runner.apply_all()
    assert postgres_database.fetch_value("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
    assert postgres_database.fetch_value("SELECT count(*) FROM atlas_meta.schema_migrations") == 1


def test_artifact_metadata_requires_verified_bytes(
    postgres_database: PostgresDatabase,
    artifact_store: ContentAddressedArtifactStore,
) -> None:
    descriptor = artifact_store.put_bytes(b"evidence", media_type="application/pdf")
    artifact_store.payload_path(descriptor.artifact_id).unlink()
    repository = ArtifactRepository(postgres_database, artifact_store)
    with pytest.raises(ArtifactIntegrityError):
        repository.register(workspace_id=WORKSPACE_ID, actor_id=ACTOR_ID, descriptor=descriptor)
    assert repository.find(descriptor.artifact_id) is None
```

- [x] **Step 2: Run RED against the real local PostgreSQL fixture**

Run:

```bash
./infra/local/postgres.sh start
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest packages/storage/tests/test_database_policy.py packages/storage/tests/test_postgres_integration.py -q
```

Expected: tests fail because the database modules, migration, and integration helper do not exist.

- [x] **Step 3: Implement socket-only settings, migration ledger, and repository**

`0001_foundation.sql` creates `vector`, `atlas_meta.schema_migrations`, immutable workspace/actor identities, and artifact metadata with SHA-256 uniqueness and explicit workspace/actor provenance. `MigrationRunner` computes and stores each migration hash, applies each migration once in a transaction, and fails if a previously applied version has different bytes.

```python
@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    conninfo: str
    socket_directory: Path

    @classmethod
    def from_conninfo(cls, conninfo: str) -> DatabaseSettings:
        parsed = conninfo_to_dict(conninfo)
        host = parsed.get("host")
        if host is None or not Path(host).is_absolute():
            raise ValueError("RSI Atlas PostgreSQL must use an absolute Unix socket directory")
        return cls(conninfo=make_conninfo(**parsed), socket_directory=Path(host))
```

All values use Psycopg parameters; identifiers in migration bookkeeping are fixed internal names. Long-lived probes use autocommit so a health `SELECT` cannot leave an idle transaction.

- [x] **Step 4: Verify migration, transaction, restart, and socket ownership behavior**

Run:

```bash
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest packages/storage/tests -q
./infra/local/postgres.sh restart
RSI_ATLAS_TEST_DATABASE_URL="$(./infra/local/postgres.sh test-url)" uv run pytest packages/storage/tests/test_postgres_integration.py -q
uv run ruff check packages/storage
uv run mypy packages/storage/src
```

Expected: migrations are idempotent, changed migration bytes fail, failed registration leaves no row, metadata survives restart, the server listens only on its owner-only Unix socket, and no TCP listener is configured.

- [x] **Step 5: Commit and review Task 2**

```bash
git add README.md infra migrations packages/storage pyproject.toml script/build_and_run.sh uv.lock
git commit -m "feat: add local PostgreSQL persistence"
```

### Task 3: Enforced runtime profiles and process capabilities

**Files:**
- Create: `packages/security/pyproject.toml`
- Create: `packages/security/src/rsi_atlas_security/__init__.py`
- Create: `packages/security/src/rsi_atlas_security/network_policy.py`
- Create: `packages/security/src/rsi_atlas_security/process_capabilities.py`
- Create: `packages/security/tests/test_network_policy.py`
- Create: `packages/security/tests/test_process_capabilities.py`
- Create: `infra/security/verify_zero_egress.py`
- Create: `infra/security/process-capabilities.json`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `NetworkPolicy`, `NetworkDecision`, `ProcessCapability`, and an auditable process-capability manifest.
- Offline mode permits owner-only Unix sockets and explicitly configured loopback services; monitored mode grants outbound access only to the collector process and allowlisted HTTPS/RPC destinations.
- Engine, parser, model, evaluation, and Codex roles default to no outbound network.

- [x] **Step 1: Write failing capability tests**

```python
@pytest.mark.parametrize("role", ["atlas-api", "atlas-worker-document", "atlas-worker-model", "atlas-worker-evaluation", "atlas-codex-controller"])
def test_non_collector_roles_cannot_open_remote_destinations(role: str) -> None:
    policy = NetworkPolicy.offline()
    decision = policy.authorize(role=role, scheme="https", host="example.com", port=443)
    assert decision.allowed is False
    assert decision.reason == "offline_profile_denies_remote_network"


def test_monitored_collector_requires_exact_allowlist_match() -> None:
    policy = NetworkPolicy.monitored(allowlisted_origins={"https://rpc.example:443"})
    assert policy.authorize(role="atlas-collector", scheme="https", host="rpc.example", port=443).allowed
    assert not policy.authorize(role="atlas-collector", scheme="https", host="evil.example", port=443).allowed
```

- [x] **Step 2: Verify RED**

Run: `uv run pytest packages/security/tests -q`

Expected: import failure because the security package does not exist.

- [x] **Step 3: Implement deterministic policy and manifest validation**

```python
@dataclass(frozen=True, slots=True)
class NetworkDecision:
    allowed: bool
    reason: str


class NetworkPolicy:
    def authorize(self, *, role: str, scheme: str, host: str, port: int) -> NetworkDecision:
        origin = canonical_origin(scheme=scheme, host=host, port=port)
        if origin in self._local_origins:
            return NetworkDecision(True, "approved_local_origin")
        if self.profile is RuntimeProfile.OFFLINE:
            return NetworkDecision(False, "offline_profile_denies_remote_network")
        if role != "atlas-collector":
            return NetworkDecision(False, "role_has_no_remote_network_capability")
        return NetworkDecision(origin in self._allowlist, "allowlisted_origin" if origin in self._allowlist else "origin_not_allowlisted")
```

Manifest validation rejects unknown roles/capabilities, wildcard destinations, private-data read grants to collectors, Keychain grants to parsers/models/Codex, and any trading/signing/wallet capability.

- [x] **Step 4: Run policy, manifest, and exact-runtime egress verification**

Run:

```bash
uv run pytest packages/security/tests -q
uv run python infra/security/verify_zero_egress.py --command "uv run atlas doctor --json"
uv run ruff check packages/security infra/security
uv run mypy packages/security/src infra/security
```

Expected: deterministic policies pass and the doctor smoke records no external DNS/TCP attempt. This is development-component evidence, not yet exact signed-release zero-egress proof.

- [x] **Step 5: Commit and review Task 3**

```bash
git add infra/security packages/security pyproject.toml uv.lock
git commit -m "feat: enforce offline runtime policy"
```

### Task 4: Local OpenTelemetry with privacy-safe storage

**Files:**
- Create: `packages/observability/pyproject.toml`
- Create: `packages/observability/src/rsi_atlas_observability/__init__.py`
- Create: `packages/observability/src/rsi_atlas_observability/tracing.py`
- Create: `packages/observability/src/rsi_atlas_observability/exporter.py`
- Create: `packages/observability/src/rsi_atlas_observability/redaction.py`
- Create: `packages/observability/tests/test_tracing.py`
- Create: `packages/observability/tests/test_redaction.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `TraceRuntime`, `LocalJSONLSpanExporter`, `PayloadMode`, and trace-context helpers.
- All spans include actor/workspace/trace identifiers but reject document bodies, prompts, credentials, analyst notes, or report text as attributes.
- Offline mode configures no exporter capable of remote transport.

- [x] **Step 1: Write failing trace and redaction tests**

```python
def test_local_exporter_persists_compact_span_without_private_payload(tmp_path: Path) -> None:
    runtime = TraceRuntime.local(tmp_path / "traces.jsonl")
    with runtime.start_as_current_span("atlas.command", context=TRACE_CONTEXT) as span:
        span.set_attribute("atlas.command.name", "Doctor")
        with pytest.raises(SensitiveTraceAttributeError):
            span.set_attribute("document.text", "private")
    runtime.shutdown()
    payload = (tmp_path / "traces.jsonl").read_text()
    assert "atlas.command" in payload
    assert "private" not in payload


def test_offline_trace_runtime_has_no_remote_exporter(tmp_path: Path) -> None:
    runtime = TraceRuntime.local(tmp_path / "traces.jsonl")
    assert runtime.export_destinations == (tmp_path / "traces.jsonl",)
```

- [x] **Step 2: Verify RED**

Run: `uv run pytest packages/observability/tests -q`

Expected: import failure because the observability package does not exist.

- [x] **Step 3: Implement local exporter and safe attribute boundary**

Use `TracerProvider`, `SimpleSpanProcessor`, and a custom `SpanExporter`. The exporter writes one canonical JSON object per completed span through a locked append, stores hashes/identifiers/timing/status only, and flushes before shutdown. The redaction boundary allowlists names and rejects sensitive namespaces rather than trying to redact arbitrary content after collection.

- [x] **Step 4: Verify trace persistence, restart, failure, and no-export behavior**

Run:

```bash
uv run pytest packages/observability/tests -q
uv run ruff check packages/observability
uv run mypy packages/observability/src
```

Expected: spans survive runtime shutdown/reopen, malformed trace storage produces an actionable diagnostic, sensitive attributes never reach disk, and no remote exporter is configured.

- [x] **Step 5: Commit and review Task 4**

```bash
git add packages/observability pyproject.toml uv.lock
git commit -m "feat: add local privacy-safe tracing"
```

Closure evidence through `01c6693`: exact import RED retained; 45 focused observability tests and 487 PostgreSQL-configured repository tests pass; Ruff, formatting, strict source mypy, lock, and diff checks pass; real multi-process initialization/append and cross-process partial-prefix poison regressions pass; current development-component zero-egress trace smoke denies external TCP and mDNS, permits the exact Unix canary, writes one owner-private canonical metadata record, and remains explicitly narrower than release proof. Independent final review approved with no findings.

### Task 5: Resource arbiter and model registry/provider boundary

**Files:**
- Create: `packages/contracts/src/rsi_atlas_contracts/models.py`
- Modify: `packages/contracts/src/rsi_atlas_contracts/__init__.py`
- Create: `packages/models/pyproject.toml`
- Create: `packages/models/src/rsi_atlas_models/__init__.py`
- Create: `packages/models/src/rsi_atlas_models/provider.py`
- Create: `packages/models/src/rsi_atlas_models/registry.py`
- Create: `packages/models/src/rsi_atlas_models/resource_arbiter.py`
- Create: `packages/models/tests/test_registry.py`
- Create: `packages/models/tests/test_resource_arbiter.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: strict `ModelArtifact`, `ModelCapability`, `ModelLifecycle`, `ModelProvider` protocol, `ModelRegistry`, `ResourceSnapshot`, `ResourcePolicy`, `ResourceLease`, and `ResourceArbiter`.
- Phase 1 registers metadata and a deterministic unavailable provider only; it does not select or download a model.
- One heavy resource lease may exist at a time; unsafe memory/swap/thermal snapshots reject admission before model load.

- [x] **Step 1: Write failing registry and arbiter tests**

```python
def test_registry_rejects_model_with_wrong_content_hash(tmp_path: Path) -> None:
    model_path = tmp_path / "model.bin"
    model_path.write_bytes(b"candidate")
    registry = ModelRegistry()
    with pytest.raises(ModelIntegrityError):
        registry.register(
            ModelArtifact(
                artifact_id=UUID("00000000-0000-0000-0000-000000000101"),
                sha256="0" * 64,
                provider_family="local_fixture",
                upstream_id="fixture/model",
                architecture="fixture",
                parameter_class="test",
                quantization="none",
                tokenizer_sha256="1" * 64,
                context_tokens=4_096,
                license_id="LicenseRef-RSIAtlas-Fixture-Model",
                source_manifest_artifact_id="sha256:" + "2" * 64,
                local_path=model_path,
                capabilities=frozenset({ModelCapability.TEXT_GENERATION}),
                lifecycle=ModelLifecycle.IMPORTED,
            )
        )


def test_only_one_heavy_lease_is_admitted() -> None:
    arbiter = ResourceArbiter(ResourcePolicy(minimum_free_bytes=4_000_000_000, maximum_swap_bytes=1_000_000_000))
    first = arbiter.acquire(job_id="research", resource_class=ResourceClass.HEAVY_MODEL, snapshot=SAFE_SNAPSHOT)
    with pytest.raises(ResourceBusyError, match="heavy model"):
        arbiter.acquire(job_id="evaluation", resource_class=ResourceClass.HEAVY_MODEL, snapshot=SAFE_SNAPSHOT)
    first.release()
    assert arbiter.acquire(job_id="evaluation", resource_class=ResourceClass.HEAVY_MODEL, snapshot=SAFE_SNAPSHOT)
```

- [x] **Step 2: Verify RED**

Run: `uv run pytest packages/models/tests -q`

Expected: import failure because the model contracts/package do not exist.

- [x] **Step 3: Implement immutable registry, provider protocol, and lease state machine**

The provider protocol exposes `capabilities`, `health`, `generate`, `stream`, and `unload`. Registry admission requires a valid artifact hash and canonical SPDX or reserved fixture license metadata; Phase 1 refuses production promotion until later typed evaluation and approval evidence exists. Resource leases are explicit context managers, release idempotently, and never infer safety from model self-report.

- [x] **Step 4: Verify integrity, lifecycle, concurrency, cancellation, and unsafe-resource cases**

Run:

```bash
uv run pytest packages/models/tests -q
uv run ruff check packages/contracts packages/models
uv run mypy packages/contracts/src packages/models/src
```

Expected: invalid hashes/lifecycle transitions fail, one-heavy-model scheduling is deterministic, released/cancelled leases free capacity, and unsafe snapshots return typed rejection.

- [x] **Step 5: Commit and review Task 5**

```bash
git add packages/contracts packages/models pyproject.toml uv.lock
git commit -m "feat: add model and resource boundaries"
```

Closure evidence through `fe5d47f`: the exact import RED is retained; 132 focused model tests and 619 PostgreSQL-configured repository tests pass; Ruff, formatting, strict source mypy, lock, and diff checks pass. Registry admission reconstructs a validated immutable snapshot, detects synchronized descriptor/parent/path replacement, accepts only canonical SPDX or the exact reserved fixture license form, and cannot promote a Phase 1 candidate to production. The unavailable provider performs no filesystem/network/subprocess work, one-heavy admission is atomic with lease-forgery/cancellation recovery coverage, and the current development-component zero-egress smoke denies external TCP and mDNS while admitting the exact local Unix canary. Independent final review approved `fe5d47f` with no Critical or Important findings. No model was downloaded, loaded, executed, benchmarked, qualified, or promoted.

### Task 6: Real diagnostics, native Command Center, and Phase 1 end-to-end gate

**Files:**
- Modify: `services/engine/pyproject.toml`
- Modify: `services/engine/src/rsi_atlas_engine/diagnostics.py`
- Modify: `services/engine/src/rsi_atlas_engine/api.py`
- Modify: `services/engine/src/rsi_atlas_engine/cli.py`
- Create: `services/engine/src/rsi_atlas_engine/runtime.py`
- Modify: `services/engine/tests/test_diagnostics.py`
- Modify: `services/engine/tests/test_api.py`
- Modify: `services/engine/tests/test_cli.py`
- Modify: `packages/contracts/src/rsi_atlas_contracts/system_status.py`
- Modify: `apps/macos/Sources/RSIAtlasCore/Models/SystemStatus.swift`
- Modify: `apps/macos/Sources/RSIAtlasApp/Views/CommandCenterView.swift`
- Modify: `apps/macos/Sources/RSIAtlasApp/Views/ComponentStatusRow.swift`
- Modify: Swift contract/store/client tests and fixture
- Modify: `script/build_and_run.sh`
- Modify: `README.md`
- Modify: `docs/production-plan.md`

**Interfaces:**
- Consumes: Tasks 1–5 probes and contracts.
- Produces: real component diagnostics for database, artifact integrity, offline policy, trace storage, resource safety, and model availability; `atlas doctor` remediation text; native grouped Command Center status.
- Overall health uses the existing explicit severity order and never reports healthy when a required Phase 1 probe is blocked, unsafe, or repairable.

- [ ] **Step 1: Write failing aggregate diagnostic and cross-language contract tests**

```python
def test_runtime_status_aggregates_real_probe_failure() -> None:
    probes = [HealthyProbe("artifact_store"), FailedProbe("database", HealthState.BLOCKED, "Initialize local PostgreSQL")]
    status = build_system_status(probes=probes, clock=FROZEN_CLOCK)
    assert status.state is HealthState.BLOCKED
    assert status.components[1].remediation == "Initialize local PostgreSQL"


def test_doctor_json_contains_all_phase_one_components() -> None:
    payload = json.loads(run_doctor_json())
    assert {item["component_id"] for item in payload["components"]} == {
        "engine_runtime", "database", "artifact_store", "offline_policy", "trace_store", "resource_policy", "model_registry", "contract_api"
    }
```

Swift fixtures assert the same schema, reject unknown fields recursively, display remediation only when present, and preserve latest-request-wins behavior.

- [ ] **Step 2: Verify RED in Python and Swift**

Run:

```bash
uv run pytest services/engine/tests -q
swift test --package-path apps/macos
```

Expected: the new probe/remediation and expanded fixture expectations fail against the three constant foundation checks.

- [ ] **Step 3: Implement dependency-injected probes and native presentation**

`RuntimeServices.from_environment()` resolves only non-secret paths/profile settings, constructs verified stores/policies, and exposes probes. The engine startup applies migrations before serving readiness. The Swift view groups Storage, Privacy, Observability, Resources, and Engine rows using native `List` sections and semantic colors; absent models display an honest degraded/non-blocking state with no download control.

- [ ] **Step 4: Run deterministic all-up checks**

Run:

```bash
uv lock --check
uv run ruff check packages services infra
uv run mypy packages services infra
uv run pytest -q
swift test --package-path apps/macos
swift build --package-path apps/macos --product RSIAtlas
bash -n script/build_and_run.sh infra/local/postgres.sh
```

Expected: all checks pass with no warnings or skipped required integration test.

- [ ] **Step 5: Run fault, egress, and foreground application smoke**

Run `./script/build_and_run.sh --verify`, inspect the foreground Command Center, stop PostgreSQL and refresh, verify an actionable blocked state, restore PostgreSQL and recover in the same window, corrupt a disposable artifact and verify repairable integrity output, restart the full stack, and record exact process/service/socket state. Run the development zero-egress verifier while `atlas doctor` and the native refresh execute.

Expected: no raw evidence is lost, the UI never fabricates health, recovery needs no source edit, and no external connection occurs.

- [ ] **Step 6: Commit, broad review, and evidence update**

```bash
git add README.md apps docs infra packages services script pyproject.toml uv.lock
git commit -m "feat: complete durable local runtime"
```

Update `docs/production-plan.md` with runtime observations, exact test counts, known release-only limitations, and the next Phase 2 blocker. Run a broad Phase 1 branch review and resolve every Critical/Important finding before marking Phase 1 complete.

## Verification

- `uv lock --check`
- `uv run ruff check packages services infra`
- `uv run mypy packages services infra`
- `uv run pytest -q`
- `swift test --package-path apps/macos`
- `swift build --package-path apps/macos --product RSIAtlas`
- `bash -n script/build_and_run.sh infra/local/postgres.sh`
- `./script/build_and_run.sh --verify`
- Manual smoke: healthy full Phase 1 status, PostgreSQL-down blocked state, same-window recovery, disposable-artifact corruption detection, relaunch persistence, and development zero-egress recording.

## Plan self-review

- Spec coverage: Tasks 1–6 cover the remaining Section 34 Phase 1 items—artifact store, PostgreSQL/pgvector, OpenTelemetry, offline policy, resource supervisor, and model registry/provider abstraction—and extend the native runtime status seam. Release IPC, XPC, embedded runtimes, signing/notarization, backup/restore, full Safe Mode, and exact release-artifact zero egress remain explicitly scheduled in Phase 6 rather than falsely claimed here.
- Placeholder scan: no task uses `TBD`, generic “add tests,” or an unnamed implementation step. Governed model/parser/provider choices remain deliberately unselected by specification, not omitted.
- Type consistency: `ArtifactDescriptor`, `DatabaseSettings`, `NetworkPolicy`, `TraceRuntime`, `ModelRegistry`, `ResourceArbiter`, and expanded `SystemStatus` are defined before consumption. Cross-language fields remain explicit `snake_case` JSON with Swift `CodingKeys`.
