"""Deterministic evaluators that precede any model judge."""

from __future__ import annotations

from typing import Any

from rsi_atlas_contracts import EvaluationExample, EvaluatorKind, EvaluatorResult


def evaluate_schema(example: EvaluationExample, actual: dict[str, Any]) -> EvaluatorResult:
    """Require actual payload keys to be a superset of expected keys."""
    missing = sorted(set(example.expected_payload) - set(actual))
    if missing:
        return EvaluatorResult(
            kind=EvaluatorKind.SCHEMA,
            passed=False,
            failure_class="schema_invalid",
            detail=f"missing keys: {','.join(missing)}",
        )
    return EvaluatorResult(kind=EvaluatorKind.SCHEMA, passed=True)


def evaluate_deterministic_rule(
    example: EvaluationExample, actual: dict[str, Any]
) -> EvaluatorResult:
    """Exact match on every expected key/value pair."""
    for key, expected in example.expected_payload.items():
        if actual.get(key) != expected:
            return EvaluatorResult(
                kind=EvaluatorKind.DETERMINISTIC_RULE,
                passed=False,
                failure_class="rule_mismatch",
                detail=f"mismatch on {key}",
            )
    return EvaluatorResult(kind=EvaluatorKind.DETERMINISTIC_RULE, passed=True)


def evaluate_exact_numerical(example: EvaluationExample, actual: dict[str, Any]) -> EvaluatorResult:
    """Compare numeric fields when expected declares numbers."""
    for key, expected in example.expected_payload.items():
        if not isinstance(expected, (int, float)):
            continue
        got = actual.get(key)
        if not isinstance(got, (int, float)) or got != expected:
            return EvaluatorResult(
                kind=EvaluatorKind.EXACT_NUMERICAL,
                passed=False,
                failure_class="numerical_mismatch",
                detail=f"numeric mismatch on {key}",
            )
    return EvaluatorResult(kind=EvaluatorKind.EXACT_NUMERICAL, passed=True)


def evaluate_retrieval_citation(
    example: EvaluationExample, actual: dict[str, Any]
) -> EvaluatorResult:
    """Require citation_ids when expected declares them."""
    expected_citations = example.expected_payload.get("citation_ids")
    if expected_citations is None:
        return EvaluatorResult(kind=EvaluatorKind.RETRIEVAL_CITATION, passed=True)
    got = actual.get("citation_ids")
    if got != expected_citations:
        return EvaluatorResult(
            kind=EvaluatorKind.RETRIEVAL_CITATION,
            passed=False,
            failure_class="citation_missing",
            detail="citation_ids mismatch",
        )
    return EvaluatorResult(kind=EvaluatorKind.RETRIEVAL_CITATION, passed=True)


def run_deterministic_evaluators(
    example: EvaluationExample, actual: dict[str, Any]
) -> tuple[EvaluatorResult, ...]:
    """Run schema → deterministic → numerical → citation; stop after first failure."""
    results: list[EvaluatorResult] = []
    for fn in (
        evaluate_schema,
        evaluate_deterministic_rule,
        evaluate_exact_numerical,
        evaluate_retrieval_citation,
    ):
        result = fn(example, actual)
        results.append(result)
        if not result.passed:
            break
    return tuple(results)
