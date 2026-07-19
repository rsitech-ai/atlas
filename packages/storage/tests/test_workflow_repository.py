"""Postgres workflow attempt persistence tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from rsi_atlas_contracts import ArtifactCommandContext
from rsi_atlas_research.workflow import (
    PostgresWorkflowStore,
    WorkflowAttempt,
    WorkflowCheckpoint,
    WorkflowStep,
    workflow_id_for_query,
)
from rsi_atlas_storage import (
    DatabaseSettings,
    MigrationRunner,
    PostgresDatabase,
    WorkflowRepository,
)

NOW = datetime(2026, 7, 19, 13, 0, tzinfo=UTC)


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


def test_workflow_repository_roundtrip(postgres_database: PostgresDatabase) -> None:
    context = _context()
    query_id = uuid4()
    workflow_id = workflow_id_for_query(query_id=query_id)
    store = PostgresWorkflowStore(
        repository=WorkflowRepository(postgres_database),
        context=context,
    )
    checkpoint = WorkflowCheckpoint(
        workflow_id=workflow_id,
        query_id=query_id,
        step=WorkflowStep.AWAITING_HUMAN,
        report_id="report:" + ("a" * 64),
        detail="awaiting review",
        updated_at=NOW,
    )
    store.save(WorkflowAttempt(checkpoint=checkpoint, title="Fees"))
    loaded = store.get(workflow_id)
    assert loaded is not None
    assert loaded.checkpoint == checkpoint
    assert loaded.title == "Fees"
    listed = store.list(limit=10)
    assert any(item.checkpoint.workflow_id == workflow_id for item in listed)
