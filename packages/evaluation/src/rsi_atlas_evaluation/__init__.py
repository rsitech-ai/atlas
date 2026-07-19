"""Offline evaluation harness and promotion gates."""

from rsi_atlas_evaluation.errors import DatasetLoadError, EvaluationError, JudgeCalibrationBlocked
from rsi_atlas_evaluation.evaluators import run_deterministic_evaluators
from rsi_atlas_evaluation.harness import default_fixture_path, load_dataset, run_offline_evaluation
from rsi_atlas_evaluation.judges import refuse_uncalibrated_judge
from rsi_atlas_evaluation.promotion import decide_promotion

__all__ = [
    "DatasetLoadError",
    "EvaluationError",
    "JudgeCalibrationBlocked",
    "decide_promotion",
    "default_fixture_path",
    "load_dataset",
    "refuse_uncalibrated_judge",
    "run_deterministic_evaluators",
    "run_offline_evaluation",
]
