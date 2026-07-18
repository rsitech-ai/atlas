from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from rsi_atlas_contracts.system_status import ComponentGroup, HealthState, SystemStatus

VALID_STATUS = {
    "schema_version": "1.1.0",
    "product": "RSI Atlas Engine",
    "profile": "offline",
    "state": "healthy",
    "checked_at": datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
    "components": [
        {
            "component_id": "engine_runtime",
            "title": "Engine Runtime",
            "group": "engine",
            "state": "healthy",
            "summary": "The local engine can evaluate runtime diagnostics.",
            "remediation": None,
        }
    ],
}


def test_system_status_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        SystemStatus.model_validate({**VALID_STATUS, "surprise": True})


def test_system_status_requires_timezone_aware_checked_at() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        SystemStatus.model_validate({**VALID_STATUS, "checked_at": "2026-07-18T12:00:00"})


def test_component_status_rejects_unknown_fields() -> None:
    payload = {
        **VALID_STATUS,
        "components": [{**VALID_STATUS["components"][0], "unexpected": "value"}],
    }

    with pytest.raises(ValidationError, match="extra_forbidden"):
        SystemStatus.model_validate(payload)


def test_system_status_requires_at_least_one_unique_component() -> None:
    with pytest.raises(ValidationError, match="too_short"):
        SystemStatus.model_validate({**VALID_STATUS, "components": []})

    duplicate = [VALID_STATUS["components"][0], VALID_STATUS["components"][0]]
    with pytest.raises(ValidationError, match="duplicate component"):
        SystemStatus.model_validate({**VALID_STATUS, "components": duplicate})


def test_system_status_rejects_inconsistent_aggregate_state() -> None:
    blocked = {
        **VALID_STATUS["components"][0],
        "component_id": "database",
        "title": "Database",
        "group": "storage",
        "state": "blocked",
        "summary": "PostgreSQL is unavailable.",
        "remediation": "Start the project-owned PostgreSQL runtime.",
    }

    with pytest.raises(ValidationError, match="highest component severity"):
        SystemStatus.model_validate({**VALID_STATUS, "state": "healthy", "components": [blocked]})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", " "),
        ("title", "x" * 81),
        ("summary", "runtime\nprivate"),
        ("summary", "x" * 241),
        ("remediation", " "),
        ("remediation", "x" * 241),
    ],
)
def test_component_text_is_bounded_nonblank_and_control_free(
    field: str,
    value: str,
) -> None:
    component = {**VALID_STATUS["components"][0], field: value}

    with pytest.raises(ValidationError):
        SystemStatus.model_validate({**VALID_STATUS, "components": [component]})


def test_closed_component_groups_and_severity_order_are_exact() -> None:
    assert tuple(group.value for group in ComponentGroup) == (
        "storage",
        "privacy",
        "observability",
        "resources",
        "engine",
    )
    assert tuple(state.value for state in HealthState) == (
        "healthy",
        "degraded",
        "blocked",
        "unsafe",
        "repairable",
    )


def test_python_contract_accepts_the_swift_fixture() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    fixture = (
        repository_root / "apps/macos/Tests/RSIAtlasCoreTests/Fixtures/system_status_v1_1.json"
    )

    status = SystemStatus.model_validate_json(fixture.read_text())

    assert status.schema_version == "1.1.0"
    assert len(status.components) == 8
    assert {component.group for component in status.components} == set(ComponentGroup)
    assert status.state is HealthState.DEGRADED
