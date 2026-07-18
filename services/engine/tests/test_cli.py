import json
from io import StringIO
from pathlib import Path

from rsi_atlas_contracts import HealthState, SystemStatus
from rsi_atlas_engine.cli import main


def _fixture_status() -> SystemStatus:
    root = Path(__file__).resolve().parents[3]
    fixture = root / "apps/macos/Tests/RSIAtlasCoreTests/Fixtures/system_status_v1_1.json"
    return SystemStatus.model_validate_json(fixture.read_text())


def _with_state(state: HealthState) -> SystemStatus:
    baseline = _fixture_status()
    component = baseline.components[0].model_copy(
        update={
            "state": state,
            "summary": f"Engine runtime is {state.value}.",
            "remediation": "Repair the local runtime."
            if state is not HealthState.HEALTHY
            else None,
        }
    )
    components = (component, *baseline.components[1:])
    priority = {
        HealthState.HEALTHY: 0,
        HealthState.DEGRADED: 1,
        HealthState.REPAIRABLE: 2,
        HealthState.BLOCKED: 3,
        HealthState.UNSAFE: 4,
    }
    aggregate = max(components, key=lambda item: priority[item.state]).state
    return SystemStatus.model_validate(
        {
            **baseline.model_dump(mode="python"),
            "state": aggregate,
            "components": components,
        }
    )


def test_doctor_json_emits_all_phase_one_components() -> None:
    expected = _fixture_status()
    output = StringIO()

    exit_code = main(
        ["doctor", "--json"],
        stdout=output,
        status_factory=lambda: expected,
    )

    payload = json.loads(output.getvalue())
    assert exit_code == 0
    assert payload == expected.model_dump(mode="json")
    assert {item["component_id"] for item in payload["components"]} == {
        "engine_runtime",
        "database",
        "artifact_store",
        "offline_policy",
        "trace_store",
        "resource_policy",
        "model_registry",
        "contract_api",
    }


def test_doctor_text_displays_remediation_and_degraded_is_operational() -> None:
    output = StringIO()

    exit_code = main(
        ["doctor"],
        stdout=output,
        status_factory=_fixture_status,
    )

    assert exit_code == 0
    assert "RSI Atlas: degraded (offline)" in output.getvalue()
    assert "Remediation: Model execution remains disabled" in output.getvalue()


def test_doctor_returns_failure_for_actionable_status() -> None:
    output = StringIO()

    exit_code = main(
        ["doctor"],
        stdout=output,
        status_factory=lambda: _with_state(HealthState.BLOCKED),
    )

    assert exit_code == 1
    assert "RSI Atlas: blocked (offline)" in output.getvalue()
