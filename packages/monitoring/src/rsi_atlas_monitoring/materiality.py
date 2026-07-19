"""Deterministic materiality screen (no semantic triage)."""

from __future__ import annotations

from decimal import Decimal

from rsi_atlas_contracts import (
    ChangeDetection,
    ChangeKind,
    MaterialityDecision,
    MaterialityOutcome,
    MonitoringRule,
)

_SEVERITY_RANK = {
    MaterialityOutcome.RECORD_ONLY: 0,
    MaterialityOutcome.LOW: 1,
    MaterialityOutcome.MEDIUM: 2,
    MaterialityOutcome.HIGH: 3,
    MaterialityOutcome.CRITICAL: 4,
    MaterialityOutcome.REQUIRES_MORE_EVIDENCE: 3,
}


def screen_materiality(
    *,
    detection: ChangeDetection,
    rule: MonitoringRule,
) -> MaterialityDecision:
    """Map detection magnitude + confidence into a materiality outcome."""
    if detection.change_kind is ChangeKind.NO_MATERIAL_CHANGE:
        return MaterialityDecision(
            outcome=MaterialityOutcome.RECORD_ONLY,
            rule_id=rule.rule_id,
            change_kind=detection.change_kind,
            magnitude="0",
            confidence=detection.confidence,
            rationale="no material change detected",
        )

    if detection.change_kind in {ChangeKind.ORPHANED, ChangeKind.QUARANTINED}:
        outcome = _raise_floor(MaterialityOutcome.HIGH, rule.severity_floor)
        return MaterialityDecision(
            outcome=outcome,
            rule_id=rule.rule_id,
            change_kind=detection.change_kind,
            magnitude="1",
            confidence=detection.confidence,
            rationale=f"{detection.change_kind.value} forces elevated materiality",
        )

    magnitude = _magnitude(detection)
    confidence = Decimal(detection.confidence)
    if magnitude >= Decimal("0.25") and confidence >= Decimal("0.9"):
        base = MaterialityOutcome.CRITICAL
    elif magnitude >= Decimal("0.10"):
        base = MaterialityOutcome.HIGH
    elif magnitude >= Decimal("0.02"):
        base = MaterialityOutcome.MEDIUM
    elif magnitude > 0:
        base = MaterialityOutcome.LOW
    else:
        base = MaterialityOutcome.RECORD_ONLY

    outcome = _raise_floor(base, rule.severity_floor)
    return MaterialityDecision(
        outcome=outcome,
        rule_id=rule.rule_id,
        change_kind=detection.change_kind,
        magnitude=format(magnitude.quantize(Decimal("0.000000000000000001")), "f"),
        confidence=detection.confidence,
        rationale=(
            f"deterministic screen magnitude={magnitude} confidence={confidence} "
            f"floor={rule.severity_floor.value}"
        ),
    )


def _magnitude(detection: ChangeDetection) -> Decimal:
    for measurement in detection.measurements:
        if measurement.delta is not None:
            previous = Decimal(measurement.previous_value)
            delta = abs(Decimal(measurement.delta))
            if previous == 0:
                return delta
            return delta / abs(previous)
    if detection.change_kind in {
        ChangeKind.FINALITY_TRANSITION,
        ChangeKind.QUALITY_TRANSITION,
    }:
        return Decimal("1")
    return Decimal("0")


def _raise_floor(
    base: MaterialityOutcome,
    floor: MaterialityOutcome,
) -> MaterialityOutcome:
    if _SEVERITY_RANK[base] >= _SEVERITY_RANK[floor]:
        return base
    return floor
