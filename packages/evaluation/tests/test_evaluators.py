"""Deterministic evaluator unit tests."""

from __future__ import annotations

from rsi_atlas_contracts import DatasetSplit, EvaluationExample, EvaluatorKind
from rsi_atlas_evaluation.evaluators import run_deterministic_evaluators


def _example() -> EvaluationExample:
    return EvaluationExample(
        example_id="ex1",
        split=DatasetSplit.REGRESSION,
        input_payload={"query": "q"},
        expected_payload={"abstain": False, "citation_ids": ["c1"], "score": 2},
    )


def test_all_pass() -> None:
    results = run_deterministic_evaluators(
        _example(), {"abstain": False, "citation_ids": ["c1"], "score": 2}
    )
    assert len(results) == 4
    assert all(result.passed for result in results)
    assert results[0].kind is EvaluatorKind.SCHEMA


def test_stops_after_schema_failure() -> None:
    results = run_deterministic_evaluators(_example(), {"score": 2})
    assert len(results) == 1
    assert results[0].passed is False
    assert results[0].failure_class == "schema_invalid"
