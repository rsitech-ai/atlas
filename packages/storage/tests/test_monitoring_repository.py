"""Monitoring repository persistence tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from rsi_atlas_collectors import import_fixture
from rsi_atlas_contracts import (
    AlertLifecycle,
    ArtifactCommandContext,
    MaterialityOutcome,
    MonitoringRule,
    MonitoringRuleType,
)
from rsi_atlas_monitoring import (
    build_alert,
    detect_observation_change,
    initial_alert_event,
    invalidate_from_detection,
    screen_materiality,
    transition_alert,
)
from rsi_atlas_storage import (
    DatabaseSettings,
    MigrationRunner,
    MonitoringRepository,
    PostgresDatabase,
)


@pytest.fixture(scope="session")
def postgres_database() -> Iterator[PostgresDatabase]:
    database = PostgresDatabase(
        DatabaseSettings.from_conninfo(os.environ["RSI_ATLAS_TEST_DATABASE_URL"])
    )
    MigrationRunner(database, Path("migrations")).apply_all()
    yield database


def _context() -> ArtifactCommandContext:
    return ArtifactCommandContext(
        tenant_id=uuid4(),
        workspace_id=uuid4(),
        actor_id=uuid4(),
        trace_id=uuid4(),
    )


def _build_alert(context: ArtifactCommandContext, now: datetime):
    first = import_fixture(context=context, fixture_name="market_tick.json", now=now)
    assert first.observation is not None
    second = import_fixture(
        context=context,
        fixture_name="market_tick.json",
        now=now + timedelta(minutes=1),
    )
    assert second.observation is not None
    current = second.observation.model_copy(
        update={
            "payload": second.observation.payload.model_copy(
                update={"last": "70000.50", "sequence": 43}
            ),
            "header": second.observation.header.model_copy(
                update={
                    "observation_id": "observation:" + ("1" * 64),
                    "envelope_id": "envelope:" + ("2" * 64),
                }
            ),
        }
    )
    detection = detect_observation_change(
        previous=first.observation,
        current=current,
        detected_at=now + timedelta(minutes=1),
    )
    rule = MonitoringRule(
        rule_id="rule:price_threshold",
        rule_type=MonitoringRuleType.THRESHOLD,
        subject_id=detection.subject_id,
        metric_name="last_price",
        threshold="65000.0",
        severity_floor=MaterialityOutcome.MEDIUM,
    )
    decision = screen_materiality(detection=detection, rule=rule)
    alert = build_alert(detection=detection, rule=rule, decision=decision)
    return alert, detection


def test_persist_alert_event_and_dedup_lookup(
    postgres_database: PostgresDatabase,
) -> None:
    now = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    context = _context()
    alert, _ = _build_alert(context, now)
    repo = MonitoringRepository(postgres_database)
    repo.save_alert(alert=alert)
    repo.save_alert_event(event=initial_alert_event(alert=alert))

    fetched = repo.get_alert(context=context, alert_id=alert.alert_id)
    assert fetched is not None
    assert fetched["alert_id"] == alert.alert_id

    by_dedup = repo.get_alert_by_dedup(context=context, dedup_key=alert.dedup_key)
    assert by_dedup is not None
    assert by_dedup["dedup_key"] == alert.dedup_key

    events = repo.list_alert_events(context=context, alert_id=alert.alert_id)
    assert len(events) == 1
    assert events[0]["to_status"] == "detected"

    updated, event = transition_alert(
        alert=alert,
        to_status=AlertLifecycle.VALIDATED,
        recorded_at=now + timedelta(minutes=2),
    )
    repo.update_alert_status(alert=updated)
    repo.save_alert_event(event=event)
    assert len(repo.list_alert_events(context=context, alert_id=alert.alert_id)) == 2


def test_persist_research_invalidation(postgres_database: PostgresDatabase) -> None:
    now = datetime(2026, 7, 19, 12, 10, tzinfo=UTC)
    context = _context()
    _, detection = _build_alert(context, now)
    record = invalidate_from_detection(
        detection=detection,
        affected_report_ids=("report:" + ("e" * 64),),
    )
    repo = MonitoringRepository(postgres_database)
    repo.save_invalidation(invalidation=record)
    listed = repo.list_invalidations(context=context, subject_id=detection.subject_id)
    assert len(listed) == 1
    assert listed[0]["invalidation_id"] == record.invalidation_id
