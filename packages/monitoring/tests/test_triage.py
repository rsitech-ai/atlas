"""Heuristic triage + calibration harness tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from rsi_atlas_contracts import SemanticTriageRequest, TriageSeverity
from rsi_atlas_monitoring import SemanticTriageBlocked, refuse_semantic_triage
from rsi_atlas_monitoring.triage import (
    TriageCalibration,
    default_calibration_path,
    load_calibration,
    run_heuristic_triage,
)

ALERT_ID = "alert:" + ("a" * 64)


def test_refuse_without_calibration_path() -> None:
    with pytest.raises(SemanticTriageBlocked):
        refuse_semantic_triage(
            SemanticTriageRequest(alert_id=ALERT_ID, change_summary="price moved")
        )


def test_uncalibrated_fails_closed() -> None:
    cal = TriageCalibration(
        calibration_id="bad",
        agreement=0.5,
        false_acceptance=0.4,
        false_rejection=0.4,
        frozen=True,
    )
    with pytest.raises(SemanticTriageBlocked, match="calibration"):
        run_heuristic_triage(
            SemanticTriageRequest(alert_id=ALERT_ID, change_summary="exploit drain"),
            calibration=cal,
        )


def test_calibrated_escalates_on_lexicon() -> None:
    cal = load_calibration(default_calibration_path())
    decision = run_heuristic_triage(
        SemanticTriageRequest(alert_id=ALERT_ID, change_summary="possible exploit and drain"),
        calibration=cal,
    )
    assert decision.severity is TriageSeverity.ESCALATE
    assert "exploit" in decision.matched_terms
    assert decision.score >= 0.9


def test_default_calibration_fixture_exists() -> None:
    path = default_calibration_path()
    assert path.is_file()
    assert Path("fixtures/monitoring") in path.parents or "fixtures" in path.parts
