# Foundation Runtime Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first RSI Atlas vertical slice: a typed offline Python runtime status contract and `atlas doctor` command, exposed over loopback and rendered by a native SwiftUI Command Center with honest loading, healthy, and unavailable states.

**Execution status:** Completed locally on `feat/andrzej_atlas_foundation`; final verification passed with 11 Python tests, 8 Swift tests, a real app launch, surviving per-user engine job, engine-down recovery, and independent re-review. No push was performed.

**Architecture:** A small Pydantic contract package remains independent of transport and UI. The Python engine computes diagnostics and exposes the same `SystemStatus` through the CLI and a development-only FastAPI loopback endpoint; the Swift package contract-tests that JSON and presents it through a focused client/store/view split. This slice intentionally excludes persistence, collectors, models, LangGraph, document ingestion, XPC, packaging, signing, and remote networking.

**Tech Stack:** Python 3.11+, uv workspace, Pydantic 2.13.4, FastAPI 0.139.2, Uvicorn 0.51.0, httpx2 2.7.0, pytest 9.1.1, Ruff 0.15.22, mypy 2.3.0; Swift 6, SwiftPM, SwiftUI, Observation, Swift Testing; macOS 15+ on Apple Silicon.

## Global Constraints

- Product name is `RSI Atlas`; Python package names use `rsi_atlas`; the CLI is `atlas`.
- Strict offline is the default profile. The engine binds only to `127.0.0.1`; no collector, remote model, telemetry exporter, update check, or remote resource is introduced.
- Health vocabulary is exactly `healthy`, `degraded`, `blocked`, `unsafe`, and `repairable`.
- Cross-boundary payloads reject unknown fields and carry schema version `1.0.0`.
- Deterministic status computation is separate from FastAPI, CLI, and SwiftUI I/O.
- The UI uses native sidebar/detail structures, semantic colors, keyboard-accessible refresh, honest error recovery, Light/Dark adaptation, and Reduce Motion-safe behavior.
- No trading, wallet, signing, or private-key capability is introduced.
- The repository remains on `feat/andrzej_atlas_foundation`; no push or PR is authorized.

---

## File Map

- `pyproject.toml`: uv workspace, shared developer tooling, and pinned dependency sources.
- `packages/contracts/`: strict Pydantic models shared by engine services.
- `services/engine/`: deterministic diagnostic service, FastAPI adapter, and `atlas` CLI.
- `apps/macos/`: SwiftPM native app, contract client, state store, SwiftUI shell, and XCTest suite.
- `script/build_and_run.sh`: single engine + app build/run entrypoint and runtime smoke.
- `.codex/environments/environment.toml`: Codex Run action.
- `docs/production-plan.md`: product, architecture, test, and readiness evidence ledger.

### Task 1: Strict Python status contract and deterministic diagnostics

**Files:**
- Create: `pyproject.toml`
- Create: `packages/contracts/pyproject.toml`
- Create: `packages/contracts/src/rsi_atlas_contracts/__init__.py`
- Create: `packages/contracts/src/rsi_atlas_contracts/system_status.py`
- Create: `packages/contracts/tests/test_system_status.py`
- Create: `services/engine/pyproject.toml`
- Create: `services/engine/src/rsi_atlas_engine/__init__.py`
- Create: `services/engine/src/rsi_atlas_engine/diagnostics.py`
- Create: `services/engine/tests/test_diagnostics.py`

**Interfaces:**
- Produces: `HealthState`, `RuntimeProfile`, `ComponentStatus`, and `SystemStatus` strict Pydantic models.
- Produces: `build_system_status(*, clock: Callable[[], datetime], components: Sequence[ComponentStatus] | None = None) -> SystemStatus`.
- Consumes: no database, network, model, or filesystem service.

- [ ] **Step 1: Write failing contract tests**

```python
def test_system_status_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        SystemStatus.model_validate({**VALID_STATUS, "surprise": True})


def test_system_status_requires_timezone_aware_checked_at() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        SystemStatus.model_validate({**VALID_STATUS, "checked_at": "2026-07-18T12:00:00"})
```

- [ ] **Step 2: Run the contract tests and verify RED**

Run: `uv run pytest packages/contracts/tests/test_system_status.py -q`

Expected: collection fails because `rsi_atlas_contracts.system_status` does not exist.

- [ ] **Step 3: Implement the strict models**

```python
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    UNSAFE = "unsafe"
    REPAIRABLE = "repairable"


class SystemStatus(StrictModel):
    schema_version: Literal["1.0.0"]
    product: Literal["RSI Atlas Engine"]
    profile: RuntimeProfile
    state: HealthState
    checked_at: AwareDatetime
    components: tuple[ComponentStatus, ...]
```

- [ ] **Step 4: Run the contract tests and verify GREEN**

Run: `uv run pytest packages/contracts/tests/test_system_status.py -q`

Expected: all contract tests pass.

- [ ] **Step 5: Write failing deterministic diagnostic tests**

```python
def test_build_system_status_defaults_to_healthy_offline_foundation() -> None:
    status = build_system_status(clock=lambda: CHECKED_AT)
    assert status.profile is RuntimeProfile.OFFLINE
    assert status.state is HealthState.HEALTHY
    assert [component.component_id for component in status.components] == [
        "engine_runtime",
        "offline_policy",
        "contract_api",
    ]


def test_build_system_status_uses_most_severe_component_state() -> None:
    status = build_system_status(clock=lambda: CHECKED_AT, components=(DEGRADED, BLOCKED))
    assert status.state is HealthState.BLOCKED
```

- [ ] **Step 6: Run diagnostic tests and verify RED**

Run: `uv run pytest services/engine/tests/test_diagnostics.py -q`

Expected: collection fails because `rsi_atlas_engine.diagnostics` does not exist.

- [ ] **Step 7: Implement minimal deterministic diagnostics**

```python
STATE_PRIORITY = {
    HealthState.HEALTHY: 0,
    HealthState.DEGRADED: 1,
    HealthState.REPAIRABLE: 2,
    HealthState.BLOCKED: 3,
    HealthState.UNSAFE: 4,
}


def build_system_status(*, clock=utc_now, components=None) -> SystemStatus:
    checks = tuple(components) if components is not None else FOUNDATION_CHECKS
    state = max((check.state for check in checks), key=STATE_PRIORITY.__getitem__)
    return SystemStatus(
        schema_version="1.0.0",
        product="RSI Atlas Engine",
        profile=RuntimeProfile.OFFLINE,
        state=state,
        checked_at=clock(),
        components=checks,
    )
```

- [ ] **Step 8: Run Python unit tests and static checks**

Run: `uv run pytest packages/contracts/tests services/engine/tests -q`

Run: `uv run ruff check packages services`

Run: `uv run mypy packages/contracts/src services/engine/src`

Expected: all commands exit zero with no diagnostics.

### Task 2: FastAPI loopback adapter and `atlas doctor`

**Files:**
- Create: `services/engine/src/rsi_atlas_engine/api.py`
- Create: `services/engine/src/rsi_atlas_engine/cli.py`
- Create: `services/engine/tests/test_api.py`
- Create: `services/engine/tests/test_cli.py`

**Interfaces:**
- Consumes: `build_system_status()` and `SystemStatus` from Task 1.
- Produces: `create_app(status_factory: Callable[[], SystemStatus]) -> FastAPI` and module-level `app`.
- Produces: `main(argv: Sequence[str] | None = None, *, stdout: TextIO = sys.stdout) -> int` with `atlas doctor [--json]`.

- [ ] **Step 1: Write the failing API test**

```python
def test_system_status_endpoint_returns_the_versioned_contract() -> None:
    client = TestClient(create_app(status_factory=lambda: EXPECTED_STATUS))
    response = client.get("/v1/system/status")
    assert response.status_code == 200
    assert response.json() == EXPECTED_STATUS.model_dump(mode="json")
```

- [ ] **Step 2: Run the API test and verify RED**

Run: `uv run pytest services/engine/tests/test_api.py -q`

Expected: collection fails because `rsi_atlas_engine.api` does not exist.

- [ ] **Step 3: Implement the FastAPI adapter**

```python
def create_app(status_factory: Callable[[], SystemStatus] = build_system_status) -> FastAPI:
    application = FastAPI(title="RSI Atlas Engine", version="0.1.0")

    @application.get("/v1/system/status", response_model=SystemStatus)
    def system_status() -> SystemStatus:
        return status_factory()

    return application


app = create_app()
```

- [ ] **Step 4: Run the API test and verify GREEN**

Run: `uv run pytest services/engine/tests/test_api.py -q`

Expected: the endpoint test passes.

- [ ] **Step 5: Write failing CLI tests**

```python
def test_doctor_json_emits_the_same_contract() -> None:
    output = StringIO()
    exit_code = main(["doctor", "--json"], stdout=output, status_factory=lambda: EXPECTED_STATUS)
    assert exit_code == 0
    assert json.loads(output.getvalue()) == EXPECTED_STATUS.model_dump(mode="json")
```

- [ ] **Step 6: Run CLI tests and verify RED**

Run: `uv run pytest services/engine/tests/test_cli.py -q`

Expected: collection fails because `rsi_atlas_engine.cli` does not exist.

- [ ] **Step 7: Implement `atlas doctor`**

```python
def main(argv=None, *, stdout=sys.stdout, status_factory=build_system_status) -> int:
    args = build_parser().parse_args(argv)
    status = status_factory()
    if args.json:
        print(status.model_dump_json(indent=2), file=stdout)
    else:
        print(f"RSI Atlas: {status.state.value} ({status.profile.value})", file=stdout)
        for component in status.components:
            print(f"- {component.title}: {component.state.value} — {component.summary}", file=stdout)
    return 0 if status.state is HealthState.HEALTHY else 1
```

- [ ] **Step 8: Verify the adapter and real CLI**

Run: `uv run pytest services/engine/tests/test_api.py services/engine/tests/test_cli.py -q`

Run: `uv run atlas doctor --json`

Expected: tests pass; the CLI prints schema version `1.0.0`, profile `offline`, state `healthy`, and three foundation components.

### Task 3: Swift contract client and state transitions

**Files:**
- Create: `apps/macos/Package.swift`
- Create: `apps/macos/Sources/RSIAtlasCore/Models/SystemStatus.swift`
- Create: `apps/macos/Sources/RSIAtlasCore/Services/EngineClient.swift`
- Create: `apps/macos/Sources/RSIAtlasCore/Stores/CommandCenterStore.swift`
- Create: `apps/macos/Tests/RSIAtlasCoreTests/Fixtures/system_status_v1.json`
- Create: `apps/macos/Tests/RSIAtlasCoreTests/SystemStatusDecodingTests.swift`
- Create: `apps/macos/Tests/RSIAtlasCoreTests/CommandCenterStoreTests.swift`

**Interfaces:**
- Produces: `SystemStatus`, `ComponentStatus`, `HealthState`, and `RuntimeProfile` `Codable`, `Sendable`, `Equatable` values.
- Produces: `EngineStatusLoading.loadStatus() async throws -> SystemStatus`.
- Produces: `@MainActor @Observable CommandCenterStore` with `state` and `reload()`.

- [ ] **Step 1: Add the canonical JSON fixture and failing decode test**

```swift
func testDecodesVersionedOfflineStatus() throws {
    let data = try fixtureData(named: "system_status_v1")
    let status = try SystemStatus.decoder.decode(SystemStatus.self, from: data)
    XCTAssertEqual(status.schemaVersion, "1.0.0")
    XCTAssertEqual(status.profile, .offline)
    XCTAssertEqual(status.state, .healthy)
    XCTAssertEqual(status.components.map(\.id), ["engine_runtime", "offline_policy", "contract_api"])
}
```

- [ ] **Step 2: Run the Swift decode test and verify RED**

Run: `swift test --package-path apps/macos --filter SystemStatusDecodingTests`

Expected: compilation fails because `SystemStatus` is undefined.

- [ ] **Step 3: Implement Swift contract values and decoder**

```swift
public struct SystemStatus: Codable, Sendable, Equatable {
    public let schemaVersion: String
    public let product: String
    public let profile: RuntimeProfile
    public let state: HealthState
    public let checkedAt: Date
    public let components: [ComponentStatus]

    public static var decoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }
}
```

- [ ] **Step 4: Run the Swift decode test and verify GREEN**

Run: `swift test --package-path apps/macos --filter SystemStatusDecodingTests`

Expected: the fixture decodes and assertions pass.

- [ ] **Step 5: Write failing store success and recovery tests**

```swift
@MainActor
func testReloadPublishesLoadedStatus() async {
    let store = CommandCenterStore(loader: StubStatusLoader(result: .success(.fixture)))
    await store.reload()
    XCTAssertEqual(store.state, .loaded(.fixture))
}

@MainActor
func testReloadPublishesRecoverableFailure() async {
    let store = CommandCenterStore(loader: StubStatusLoader(result: .failure(TestError.offline)))
    await store.reload()
    XCTAssertEqual(store.state, .failed(message: "RSI Atlas Engine is unavailable."))
}
```

- [ ] **Step 6: Run store tests and verify RED**

Run: `swift test --package-path apps/macos --filter CommandCenterStoreTests`

Expected: compilation fails because `CommandCenterStore` and `EngineStatusLoading` are undefined.

- [ ] **Step 7: Implement the client and observable store**

```swift
public protocol EngineStatusLoading: Sendable {
    func loadStatus() async throws -> SystemStatus
}

@MainActor
@Observable
public final class CommandCenterStore {
    public private(set) var state: LoadState = .idle
    private let loader: any EngineStatusLoading

    public func reload() async {
        state = .loading
        do { state = .loaded(try await loader.loadStatus()) }
        catch { state = .failed(message: "RSI Atlas Engine is unavailable.") }
    }
}
```

- [ ] **Step 8: Run all Swift core tests**

Run: `swift test --package-path apps/macos`

Expected: decoding and store tests pass without warnings.

### Task 4: Native Command Center shell

**Files:**
- Create: `apps/macos/Sources/RSIAtlasApp/App/RSIAtlasApp.swift`
- Create: `apps/macos/Sources/RSIAtlasApp/Models/WorkspaceDestination.swift`
- Create: `apps/macos/Sources/RSIAtlasApp/Views/ContentView.swift`
- Create: `apps/macos/Sources/RSIAtlasApp/Views/SidebarView.swift`
- Create: `apps/macos/Sources/RSIAtlasApp/Views/CommandCenterView.swift`
- Create: `apps/macos/Sources/RSIAtlasApp/Views/ComponentStatusRow.swift`

**Interfaces:**
- Consumes: `CommandCenterStore`, `SystemStatus`, and `EngineClient` from Task 3.
- Produces: a `WindowGroup` app with native `NavigationSplitView`, one live Command Center destination, toolbar refresh, `⌘R`, and error retry.

- [ ] **Step 1: Add the minimal multi-file SwiftUI shell**

```swift
@main
struct RSIAtlasApp: App {
    var body: some Scene {
        WindowGroup("RSI Atlas") {
            ContentView(store: CommandCenterStore(loader: EngineClient()))
                .frame(minWidth: 860, minHeight: 600)
        }
        .defaultSize(width: 1120, height: 760)
    }
}
```

```swift
NavigationSplitView {
    SidebarView(selection: $selection)
} detail: {
    CommandCenterView(store: store)
}
```

- [ ] **Step 2: Implement complete status states without dead controls**

```swift
switch store.state {
case .idle, .loading:
    ProgressView("Checking local runtime…")
case let .loaded(status):
    List(status.components) { ComponentStatusRow(component: $0) }
case let .failed(message):
    ContentUnavailableView {
        Label("Engine unavailable", systemImage: "exclamationmark.triangle")
    } description: {
        Text(message)
    } actions: {
        Button("Retry") { Task { await store.reload() } }
    }
}
```

- [ ] **Step 3: Build the native executable**

Run: `swift build --package-path apps/macos`

Expected: product `RSIAtlas` builds without compiler warnings or errors.

- [ ] **Step 4: Run Swift tests after UI integration**

Run: `swift test --package-path apps/macos`

Expected: all Swift tests remain green.

### Task 5: Reproducible build/run and product evidence

**Files:**
- Create: `script/build_and_run.sh`
- Create: `.codex/environments/environment.toml`
- Create: `docs/production-plan.md`
- Modify: `README.md`
- Create: `.gitignore`

**Interfaces:**
- Consumes: `uv run uvicorn rsi_atlas_engine.api:app` and SwiftPM product `RSIAtlas`.
- Produces: `./script/build_and_run.sh [run|--debug|--logs|--telemetry|--verify]`.
- Produces: project-local `dist/RSIAtlas.app` and `dist/engine.log`, both ignored by Git.

- [ ] **Step 1: Add the single project-local run entrypoint**

```bash
ENGINE_HOST="127.0.0.1"
ENGINE_PORT="8765"
uv sync --all-packages
uv run uvicorn rsi_atlas_engine.api:app --host "$ENGINE_HOST" --port "$ENGINE_PORT" >"$ENGINE_LOG" 2>&1 &
ENGINE_PID=$!
printf '%s\n' "$ENGINE_PID" >"$ENGINE_PID_FILE"
swift build --package-path "$ROOT_DIR/apps/macos"
```

The script must stop only the prior app process and the PID recorded in its own `dist/atlas-engine.pid`, poll `http://127.0.0.1:8765/v1/system/status`, stage `dist/RSIAtlas.app` with bundle identifier `ai.rsitech.RSIAtlas`, and support the canonical mode flags.

- [ ] **Step 2: Add the Codex Run action**

```toml
# THIS IS AUTOGENERATED. DO NOT EDIT MANUALLY
version = 1
name = "RSI Atlas"

[setup]
script = ""

[[actions]]
name = "Run"
icon = "run"
command = "./script/build_and_run.sh"
```

- [ ] **Step 3: Document product and readiness truth**

Record the target user, research-only scope, macOS 15+ floor, strict offline default, native shell architecture, exact verification commands, logging exclusions, and explicit blockers for PostgreSQL, XPC, persistence, signing, notarization, collectors, models, and release qualification in `docs/production-plan.md` and `README.md`.

- [ ] **Step 4: Run the full deterministic verification suite**

Run: `uv lock --check`

Run: `uv run ruff check packages services`

Run: `uv run mypy packages/contracts/src services/engine/src`

Run: `uv run pytest -q`

Run: `swift test --package-path apps/macos`

Run: `swift build --package-path apps/macos`

Expected: every command exits zero with clean output.

- [ ] **Step 5: Run the real app smoke**

Run: `./script/build_and_run.sh --verify`

Expected: the engine health endpoint returns HTTP 200; `RSIAtlas` is running from `dist/RSIAtlas.app`; the native Command Center displays the offline healthy foundation status.

- [ ] **Step 6: Inspect and record runtime evidence**

Inspect the foreground app at minimum and typical window sizes, retry once with the engine intentionally stopped to prove the recoverable unavailable state, relaunch the full stack, and add the exact observations to the production-plan iteration log. Mark Light/Dark, VoiceOver, large text, increased contrast, and release signing as unverified unless directly exercised.

## Verification

- `uv lock --check`
- `uv run ruff check packages services`
- `uv run mypy packages/contracts/src services/engine/src`
- `uv run pytest -q`
- `uv run atlas doctor --json`
- `swift test --package-path apps/macos`
- `swift build --package-path apps/macos`
- `./script/build_and_run.sh --verify`
- Manual smoke: healthy foundation state, engine-unavailable recovery, minimum/typical window behavior, foreground relaunch.

## Plan Self-Review

- Spec coverage: this plan covers only the first Phase 1 contract/UI/runtime seam. PostgreSQL, artifact storage, OpenTelemetry, resource supervision, and model registry remain separate vertical slices.
- Placeholders: none; deferred capabilities are named as explicit non-goals or blockers.
- Type consistency: Python `snake_case` keys map through Swift `.convertFromSnakeCase`; enum values and schema version match exactly.
- Dependency direction: contracts know no transport or UI; engine adapters depend on contracts; Swift core knows no SwiftUI; SwiftUI depends on the core client/store.

## Decision Log

- 2026-07-18: Replace the planned `httpx 0.28.1` test dependency with `httpx2 2.7.0`; FastAPI 0.139.2's Starlette test client emitted a deprecation warning when only the legacy package was installed.
- 2026-07-18: Use a labeled per-user `launchctl` job rather than a shell-backgrounded child; separate-shell checks proved this execution host reaped both plain and `nohup` descendants.
- 2026-07-18: Match app lifecycle operations to the exact staged binary path, validate launcher mode before side effects, and use latest-request-wins status publication after independent review exposed the weaker boundaries.

## Commit Boundary

After all verification passes, one local commit may include the approved design, this plan, and the intentional foundation files with message `feat: bootstrap RSI Atlas foundation`. Do not push.
