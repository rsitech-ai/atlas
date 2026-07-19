"""Loopback monitoring and comparison API contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from rsi_atlas_collectors import import_fixture, mark_orphaned
from rsi_atlas_contracts import (
    ArtifactCommandContext,
    MaterialityOutcome,
    MonitoringRule,
    MonitoringRuleType,
    QueryFamily,
    RetrievalDataPlane,
    RetrievalPlan,
    RetrievalStep,
    retrieval_plan_hash,
)
from rsi_atlas_engine.api import create_app
from rsi_atlas_engine.monitoring import InMemoryMonitoringService

TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000002")
ACTOR_ID = UUID("00000000-0000-4000-8000-000000000003")
TRACE_ID = UUID("00000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def _headers() -> dict[str, str]:
    return {
        "x-rsi-tenant-id": str(TENANT_ID),
        "x-rsi-actor-id": str(ACTOR_ID),
        "x-rsi-trace-id": str(TRACE_ID),
    }


def _context() -> ArtifactCommandContext:
    return ArtifactCommandContext(
        tenant_id=TENANT_ID,
        workspace_id=WORKSPACE_ID,
        actor_id=ACTOR_ID,
        trace_id=TRACE_ID,
    )


def _market_pair():
    context = _context()
    first = import_fixture(context=context, fixture_name="market_tick.json", now=NOW)
    assert first.observation is not None
    second = import_fixture(
        context=context,
        fixture_name="market_tick.json",
        now=NOW + timedelta(minutes=1),
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
    return first.observation, current


def test_evaluate_transition_invalidate_comparison_and_triage() -> None:
    client = TestClient(create_app(monitoring_service=InMemoryMonitoringService()))
    previous, current = _market_pair()
    rule = MonitoringRule(
        rule_id="rule:price_threshold",
        rule_type=MonitoringRuleType.THRESHOLD,
        subject_id=current.header.subject_ids[0],
        metric_name="last_price",
        threshold="65000.0",
        severity_floor=MaterialityOutcome.MEDIUM,
    )
    evaluate = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/monitoring:evaluate",
        headers=_headers(),
        json={
            "previous_observation": previous.model_dump(mode="json"),
            "current_observation": current.model_dump(mode="json"),
            "rules": [rule.model_dump(mode="json")],
            "affected_report_ids": ["report:" + ("e" * 64)],
        },
    )
    assert evaluate.status_code == 200
    body = evaluate.json()
    assert body["detection"]["change_kind"] == "rate_of_change"
    assert len(body["alerts"]) == 1
    alert_id = body["alerts"][0]["alert_id"]

    transition = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/monitoring/alerts/{alert_id}:transition",
        headers=_headers(),
        json={"to_status": "validated"},
    )
    assert transition.status_code == 200
    assert transition.json()["alert"]["status"] == "validated"

    context = _context()
    btc = import_fixture(context=context, fixture_name="bitcoin_block.json", now=NOW)
    assert btc.observation is not None
    orphaned = mark_orphaned(btc.observation)
    invalidate = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/monitoring:invalidate",
        headers=_headers(),
        json={
            "previous_observation": btc.observation.model_dump(mode="json"),
            "current_observation": orphaned.model_dump(mode="json"),
            "affected_report_ids": ["report:" + ("e" * 64)],
            "alert_id": alert_id,
        },
    )
    assert invalidate.status_code == 200
    assert invalidate.json()["invalidation"]["reason"] == "orphaned_observation"

    query_id = uuid4()
    steps = (
        RetrievalStep(
            step_id="dense_main",
            data_plane=RetrievalDataPlane.DENSE_DOCUMENT,
            retriever="fixture_dense",
            query_text="material change",
            top_k=8,
            required=True,
            expected_evidence="passages",
        ),
    )
    plan = RetrievalPlan(
        plan_id=uuid4(),
        query_id=query_id,
        query_family=QueryFamily.EVENT_INVESTIGATION,
        steps=steps,
        plan_hash=retrieval_plan_hash(
            query_id=query_id,
            query_family=QueryFamily.EVENT_INVESTIGATION,
            steps=steps,
        ),
    )
    launch = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/monitoring:launch-research",
        headers=_headers(),
        json={"alert_id": alert_id, "plan": plan.model_dump(mode="json")},
    )
    assert launch.status_code == 200
    assert launch.json()["launch"]["status"] == "recorded_stub"

    comparison = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/monitoring:comparison",
        headers=_headers(),
        json={
            "observations": [
                btc.observation.model_dump(mode="json"),
                current.model_dump(mode="json"),
            ],
            "axes": ["source_family", "quality"],
            "as_of": "2026-07-19T12:00:00Z",
        },
    )
    assert comparison.status_code == 200
    assert comparison.json()["matrix"]["cells"]

    timeline = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/monitoring:timeline",
        headers=_headers(),
        json={
            "observations": [btc.observation.model_dump(mode="json")],
            "as_of": "2026-07-19T12:00:00Z",
        },
    )
    assert timeline.status_code == 200
    assert timeline.json()["timeline"]["events"]

    triage = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/monitoring:semantic-triage",
        headers=_headers(),
        json={"alert_id": alert_id, "change_summary": "needs model"},
    )
    assert triage.status_code == 422
    assert triage.json()["detail"] == "blocked_semantic_triage"


def test_missing_monitoring_service_is_unavailable() -> None:
    client = TestClient(create_app())
    response = client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/monitoring:evaluate",
        headers=_headers(),
        json={},
    )
    assert response.status_code == 503
