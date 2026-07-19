"""Monitoring evaluation service for development loopback APIs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from rsi_atlas_contracts import (
    Alert,
    AlertEvent,
    AlertLifecycle,
    ArtifactCommandContext,
    ComparisonAxis,
    ComparisonMatrix,
    CrossChainTimeline,
    MaterialityDecision,
    MonitoringRule,
    Observation,
    ResearchInvalidation,
    RetrievalPlan,
    SemanticTriageDecision,
    SemanticTriageRequest,
    TargetedResearchLaunch,
)
from rsi_atlas_monitoring import (
    AlertTransitionError,
    SemanticTriageBlocked,
    build_alert,
    build_comparison_matrix,
    build_cross_chain_timeline,
    dedupe_or_create,
    detect_observation_change,
    initial_alert_event,
    invalidate_from_detection,
    launch_targeted_research,
    match_rules,
    run_heuristic_triage,
    screen_materiality,
    transition_alert,
)
from rsi_atlas_storage import MonitoringRepository, PostgresDatabase


class MonitoringPort(Protocol):
    def evaluate_change(
        self,
        *,
        context: ArtifactCommandContext,
        previous: Observation | None,
        current: Observation,
        rules: tuple[MonitoringRule, ...],
        affected_report_ids: tuple[str, ...] = (),
    ) -> dict[str, object]: ...

    def transition(
        self,
        *,
        context: ArtifactCommandContext,
        alert_id: str,
        to_status: AlertLifecycle,
        note: str = "",
    ) -> dict[str, object]: ...

    def invalidate(
        self,
        *,
        context: ArtifactCommandContext,
        previous: Observation | None,
        current: Observation,
        affected_report_ids: tuple[str, ...] = (),
        alert_id: str | None = None,
    ) -> ResearchInvalidation: ...

    def launch(
        self,
        *,
        context: ArtifactCommandContext,
        alert_id: str,
        plan: RetrievalPlan,
    ) -> TargetedResearchLaunch: ...

    def comparison(
        self,
        *,
        context: ArtifactCommandContext,
        observations: tuple[Observation, ...],
        axes: tuple[ComparisonAxis, ...],
        as_of: datetime,
    ) -> ComparisonMatrix: ...

    def timeline(
        self,
        *,
        context: ArtifactCommandContext,
        observations: tuple[Observation, ...],
        as_of: datetime,
    ) -> CrossChainTimeline: ...

    def triage(self, *, request: SemanticTriageRequest) -> SemanticTriageDecision: ...


@dataclass
class InMemoryMonitoringService:
    """Loopback-friendly monitoring service with optional repository persistence."""

    repository: MonitoringRepository | None = None
    _alerts: dict[str, Alert] = field(default_factory=dict)
    _by_dedup: dict[str, Alert] = field(default_factory=dict)
    _events: dict[str, list[AlertEvent]] = field(default_factory=dict)
    _invalidations: list[ResearchInvalidation] = field(default_factory=list)
    _launches: list[TargetedResearchLaunch] = field(default_factory=list)

    @classmethod
    def from_database(cls, database: PostgresDatabase) -> InMemoryMonitoringService:
        return cls(repository=MonitoringRepository(database))

    def evaluate_change(
        self,
        *,
        context: ArtifactCommandContext,
        previous: Observation | None,
        current: Observation,
        rules: tuple[MonitoringRule, ...],
        affected_report_ids: tuple[str, ...] = (),
    ) -> dict[str, object]:
        del context  # identity comes from observation.context
        detected_at = datetime.now(tz=UTC)
        detection = detect_observation_change(
            previous=previous,
            current=current,
            detected_at=detected_at,
        )
        matched = match_rules(detection=detection, rules=rules)
        decisions: list[MaterialityDecision] = []
        alerts: list[Alert] = []
        created_flags: list[bool] = []
        for rule in matched:
            decision = screen_materiality(detection=detection, rule=rule)
            decisions.append(decision)
            if decision.outcome.value == "record_only":
                continue
            candidate = build_alert(
                detection=detection,
                rule=rule,
                decision=decision,
                affected_report_ids=affected_report_ids,
            )
            existing = self._by_dedup.copy()
            if self.repository is not None:
                row = self.repository.get_alert_by_dedup(
                    context=current.context,
                    dedup_key=candidate.dedup_key,
                )
                if row is not None:
                    existing[candidate.dedup_key] = Alert.model_validate(row)
            alert, created = dedupe_or_create(candidate=candidate, existing_by_dedup=existing)
            created_flags.append(created)
            if created:
                event = initial_alert_event(alert=alert)
                self._alerts[alert.alert_id] = alert
                self._by_dedup[alert.dedup_key] = alert
                self._events.setdefault(alert.alert_id, []).append(event)
                if self.repository is not None:
                    self.repository.save_alert(alert=alert)
                    self.repository.save_alert_event(event=event)
            alerts.append(alert)
        return {
            "detection": detection,
            "matched_rules": matched,
            "decisions": decisions,
            "alerts": alerts,
            "created": created_flags,
        }

    def transition(
        self,
        *,
        context: ArtifactCommandContext,
        alert_id: str,
        to_status: AlertLifecycle,
        note: str = "",
    ) -> dict[str, object]:
        alert = self._alerts.get(alert_id)
        if alert is None and self.repository is not None:
            row = self.repository.get_alert(context=context, alert_id=alert_id)
            if row is not None:
                alert = Alert.model_validate(row)
        if alert is None:
            raise LookupError("alert not found")
        updated, event = transition_alert(
            alert=alert,
            to_status=to_status,
            recorded_at=datetime.now(tz=UTC),
            note=note,
        )
        self._alerts[updated.alert_id] = updated
        self._by_dedup[updated.dedup_key] = updated
        self._events.setdefault(updated.alert_id, []).append(event)
        if self.repository is not None:
            self.repository.update_alert_status(alert=updated)
            self.repository.save_alert_event(event=event)
        return {"alert": updated, "event": event}

    def invalidate(
        self,
        *,
        context: ArtifactCommandContext,
        previous: Observation | None,
        current: Observation,
        affected_report_ids: tuple[str, ...] = (),
        alert_id: str | None = None,
    ) -> ResearchInvalidation:
        del context
        detection = detect_observation_change(
            previous=previous,
            current=current,
            detected_at=datetime.now(tz=UTC),
        )
        record = invalidate_from_detection(
            detection=detection,
            affected_report_ids=affected_report_ids,
            alert_id=alert_id,
        )
        self._invalidations.append(record)
        if self.repository is not None:
            self.repository.save_invalidation(invalidation=record)
        return record

    def launch(
        self,
        *,
        context: ArtifactCommandContext,
        alert_id: str,
        plan: RetrievalPlan,
    ) -> TargetedResearchLaunch:
        alert = self._alerts.get(alert_id)
        if alert is None and self.repository is not None:
            row = self.repository.get_alert(context=context, alert_id=alert_id)
            if row is not None:
                alert = Alert.model_validate(row)
        if alert is None:
            raise LookupError("alert not found")
        launch = launch_targeted_research(
            alert=alert,
            plan=plan,
            recorded_at=datetime.now(tz=UTC),
        )
        self._launches.append(launch)
        return launch

    def comparison(
        self,
        *,
        context: ArtifactCommandContext,
        observations: tuple[Observation, ...],
        axes: tuple[ComparisonAxis, ...],
        as_of: datetime,
    ) -> ComparisonMatrix:
        return build_comparison_matrix(
            context=context,
            observations=observations,
            axes=axes,
            as_of=as_of,
        )

    def timeline(
        self,
        *,
        context: ArtifactCommandContext,
        observations: tuple[Observation, ...],
        as_of: datetime,
    ) -> CrossChainTimeline:
        alerts = tuple(self._alerts.values())
        return build_cross_chain_timeline(
            context=context,
            observations=observations,
            alerts=alerts,
            as_of=as_of,
        )

    def triage(self, *, request: SemanticTriageRequest) -> SemanticTriageDecision:
        return run_heuristic_triage(request)


__all__ = [
    "AlertTransitionError",
    "InMemoryMonitoringService",
    "MonitoringPort",
    "SemanticTriageBlocked",
]
