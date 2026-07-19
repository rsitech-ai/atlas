"""Offline evaluation harness errors."""

from __future__ import annotations


class EvaluationError(RuntimeError):
    """Base evaluation-plane error."""


class JudgeCalibrationBlocked(EvaluationError):
    def __init__(self, reason: str = "blocked_judge_uncalibrated") -> None:
        self.code = reason
        super().__init__(reason)


class DatasetLoadError(EvaluationError):
    def __init__(self, reason: str) -> None:
        self.code = "dataset_load_error"
        super().__init__(reason)
