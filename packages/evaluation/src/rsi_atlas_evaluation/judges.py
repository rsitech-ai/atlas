"""Fail-closed LLM judge stub until calibrated labelled sets exist."""

from __future__ import annotations

from rsi_atlas_contracts import JudgeCalibrationGate

from rsi_atlas_evaluation.errors import JudgeCalibrationBlocked


def refuse_uncalibrated_judge() -> JudgeCalibrationGate:
    """LLM judges remain blocked in the Phase 6 development slice."""
    gate = JudgeCalibrationGate()
    raise JudgeCalibrationBlocked(gate.reason)
