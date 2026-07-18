from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from rsi_atlas_contracts.system_status import SystemStatus

VALID_STATUS = {
    "schema_version": "1.0.0",
    "product": "RSI Atlas Engine",
    "profile": "offline",
    "state": "healthy",
    "checked_at": datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
    "components": [
        {
            "component_id": "engine_runtime",
            "title": "Engine Runtime",
            "state": "healthy",
            "summary": "The local engine can evaluate foundation diagnostics.",
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


def test_system_status_requires_at_least_one_component() -> None:
    with pytest.raises(ValidationError, match="too_short"):
        SystemStatus.model_validate({**VALID_STATUS, "components": []})


def test_python_contract_accepts_the_swift_fixture() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    fixture = repository_root / "apps/macos/Tests/RSIAtlasCoreTests/Fixtures/system_status_v1.json"

    status = SystemStatus.model_validate_json(fixture.read_text())

    assert status.schema_version == "1.0.0"
    assert len(status.components) == 3
