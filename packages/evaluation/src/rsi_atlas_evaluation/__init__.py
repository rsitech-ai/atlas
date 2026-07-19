"""Offline evaluation harness and promotion gates."""

from rsi_atlas_evaluation.errors import DatasetLoadError, EvaluationError, JudgeCalibrationBlocked
from rsi_atlas_evaluation.evaluators import run_deterministic_evaluators
from rsi_atlas_evaluation.harness import default_fixture_path, load_dataset, run_offline_evaluation
from rsi_atlas_evaluation.judges import refuse_uncalibrated_judge
from rsi_atlas_evaluation.promotion import decide_promotion
from rsi_atlas_evaluation.sealed_promotion import (
    SealedPromotionBlocked,
    default_sealed_fixture_path,
    require_production_authorization,
    run_sealed_promotion,
    write_development_sealed_package,
)

__all__ = [
    "DatasetLoadError",
    "EvaluationError",
    "JudgeCalibrationBlocked",
    "SealedPromotionBlocked",
    "decide_promotion",
    "default_fixture_path",
    "default_sealed_fixture_path",
    "load_dataset",
    "refuse_uncalibrated_judge",
    "require_production_authorization",
    "run_deterministic_evaluators",
    "run_offline_evaluation",
    "run_sealed_promotion",
    "write_development_sealed_package",
]
