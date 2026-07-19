"""Deterministic retrieval plan validation for the development slice."""

from __future__ import annotations

from rsi_atlas_contracts import (
    DEVELOPMENT_RETRIEVAL_PLANES,
    RetrievalPlan,
    RetrievalStep,
)


class PlanValidationError(ValueError):
    """Raised when a retrieval plan violates development policy."""


def validate_retrieval_plan(plan: RetrievalPlan) -> RetrievalPlan:
    """Validate fan-out, planes, and required steps without LLM planning."""
    if not plan.steps:
        raise PlanValidationError("plan requires at least one step")
    if len(plan.steps) > 16:
        raise PlanValidationError("plan exceeds development fan-out limit")
    step_ids: set[str] = set()
    for step in plan.steps:
        _validate_step(step)
        if step.step_id in step_ids:
            raise PlanValidationError(f"duplicate step_id {step.step_id}")
        step_ids.add(step.step_id)
    required = [step for step in plan.steps if step.required]
    if not required:
        raise PlanValidationError("plan requires at least one required step")
    return plan


def _validate_step(step: RetrievalStep) -> None:
    if step.data_plane not in DEVELOPMENT_RETRIEVAL_PLANES:
        raise PlanValidationError(f"data plane {step.data_plane} is blocked")
    if step.top_k > 200:
        raise PlanValidationError("top_k exceeds development budget")
    if not step.query_text.strip():
        raise PlanValidationError("step query_text is empty")
