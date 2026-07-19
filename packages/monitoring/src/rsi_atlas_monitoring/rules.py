"""Rule matching for development monitoring rule types."""

from __future__ import annotations

from decimal import Decimal

from rsi_atlas_contracts import (
    BLOCKED_RULE_TYPES,
    ChangeDetection,
    ChangeKind,
    MonitoringRule,
    MonitoringRuleType,
)

from rsi_atlas_monitoring.errors import RuleMatchError


def match_rules(
    *,
    detection: ChangeDetection,
    rules: tuple[MonitoringRule, ...],
) -> tuple[MonitoringRule, ...]:
    """Return enabled rules that fire for this deterministic detection."""
    matched: list[MonitoringRule] = []
    for rule in rules:
        if not rule.enabled:
            continue
        if rule.rule_type in BLOCKED_RULE_TYPES:
            raise RuleMatchError(
                f"rule_type {rule.rule_type.value} remains blocked without governance"
            )
        if rule.subject_id != detection.subject_id:
            continue
        if _rule_matches(rule=rule, detection=detection):
            matched.append(rule)
    return tuple(matched)


def _rule_matches(*, rule: MonitoringRule, detection: ChangeDetection) -> bool:
    if rule.rule_type is MonitoringRuleType.THRESHOLD:
        if detection.change_kind not in {
            ChangeKind.RATE_OF_CHANGE,
            ChangeKind.THRESHOLD_BREACH,
        }:
            return False
        if rule.threshold is None:
            raise RuleMatchError("threshold rule missing threshold")
        for measurement in detection.measurements:
            if measurement.name != rule.metric_name:
                continue
            if Decimal(measurement.current_value) >= Decimal(rule.threshold):
                return True
        return False

    if rule.rule_type is MonitoringRuleType.RATE_OF_CHANGE:
        return detection.change_kind is ChangeKind.RATE_OF_CHANGE and any(
            measurement.name == rule.metric_name for measurement in detection.measurements
        )

    if rule.rule_type is MonitoringRuleType.STATE_TRANSITION:
        return detection.change_kind in {
            ChangeKind.FINALITY_TRANSITION,
            ChangeKind.ORPHANED,
        }

    if rule.rule_type is MonitoringRuleType.QUALITY_TRANSITION:
        return detection.change_kind in {
            ChangeKind.QUALITY_TRANSITION,
            ChangeKind.QUARANTINED,
        }

    raise RuleMatchError(f"unsupported rule_type {rule.rule_type.value}")
