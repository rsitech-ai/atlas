"""Fail-closed semantic triage stub."""

from __future__ import annotations

from rsi_atlas_contracts import SemanticTriageGate, SemanticTriageRequest

from rsi_atlas_monitoring.errors import SemanticTriageBlocked


def refuse_semantic_triage(request: SemanticTriageRequest) -> SemanticTriageGate:
    """Semantic triage remains blocked until calibrated models are promoted."""
    del request  # request shape is validated by the contract; never executed.
    gate = SemanticTriageGate()
    raise SemanticTriageBlocked(gate.reason)
