"""Targeted research launch stub (plan validation only; no LangGraph)."""

from __future__ import annotations

from datetime import datetime

from rsi_atlas_contracts import (
    Alert,
    RetrievalPlan,
    TargetedResearchLaunch,
    retrieval_plan_hash,
    targeted_research_launch_id,
)
from rsi_atlas_research import PlanValidationError, validate_retrieval_plan

from rsi_atlas_monitoring.errors import LaunchValidationError


def launch_targeted_research(
    *,
    alert: Alert,
    plan: RetrievalPlan,
    recorded_at: datetime,
) -> TargetedResearchLaunch:
    """Validate a Phase 3 plan shape and record a launch stub (no graph run)."""
    try:
        validated = validate_retrieval_plan(plan)
    except PlanValidationError as error:
        raise LaunchValidationError(str(error)) from error
    expected = retrieval_plan_hash(
        query_id=validated.query_id,
        query_family=validated.query_family,
        steps=validated.steps,
    )
    if validated.plan_hash != expected:
        raise LaunchValidationError("plan_hash mismatch after validation")
    return TargetedResearchLaunch(
        context=alert.context,
        launch_id=targeted_research_launch_id(
            alert_id_value=alert.alert_id,
            plan_hash=validated.plan_hash,
        ),
        alert_id=alert.alert_id,
        subject_id=alert.subject_id,
        plan_hash=validated.plan_hash,
        recorded_at=recorded_at,
    )
