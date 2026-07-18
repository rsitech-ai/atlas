import json
from datetime import UTC, datetime
from io import StringIO

from rsi_atlas_contracts import ComponentStatus, HealthState, RuntimeProfile, SystemStatus
from rsi_atlas_engine.cli import main


def make_status(state: HealthState = HealthState.HEALTHY) -> SystemStatus:
    return SystemStatus(
        schema_version="1.0.0",
        product="RSI Atlas Engine",
        profile=RuntimeProfile.OFFLINE,
        state=state,
        checked_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
        components=(
            ComponentStatus(
                component_id="engine_runtime",
                title="Engine Runtime",
                state=state,
                summary="The local engine can evaluate foundation diagnostics.",
            ),
        ),
    )


def test_doctor_json_emits_the_same_contract() -> None:
    expected = make_status()
    output = StringIO()

    exit_code = main(
        ["doctor", "--json"],
        stdout=output,
        status_factory=lambda: expected,
    )

    assert exit_code == 0
    assert json.loads(output.getvalue()) == expected.model_dump(mode="json")


def test_doctor_returns_failure_for_nonhealthy_status() -> None:
    output = StringIO()

    exit_code = main(
        ["doctor"],
        stdout=output,
        status_factory=lambda: make_status(HealthState.BLOCKED),
    )

    assert exit_code == 1
    assert "RSI Atlas: blocked (offline)" in output.getvalue()
