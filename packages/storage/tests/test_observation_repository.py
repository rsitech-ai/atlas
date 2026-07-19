"""Observation repository persistence tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from json import loads
from pathlib import Path
from uuid import uuid4

import pytest
from rsi_atlas_collectors import import_fixture, mark_orphaned
from rsi_atlas_contracts import ArtifactCommandContext, ProviderQualityState
from rsi_atlas_storage import (
    DatabaseSettings,
    MigrationRunner,
    ObservationRepository,
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


def test_persist_envelope_observation_and_as_of(
    postgres_database: PostgresDatabase,
) -> None:
    now = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    context = _context()
    result = import_fixture(context=context, fixture_name="bitcoin_block.json", now=now)
    assert result.observation is not None
    repo = ObservationRepository(postgres_database)
    repo.save_envelope(
        envelope=result.envelope,
        payload=loads(result.payload_bytes.decode("utf-8")),
    )
    repo.save_observation(observation=result.observation)

    fetched = repo.get_observation(
        context=context,
        observation_id=result.observation.header.observation_id,
    )
    assert fetched is not None
    assert fetched["header"]["observation_id"] == result.observation.header.observation_id

    visible = repo.list_as_of(context=context, as_of=now)
    assert len(visible) == 1
    hidden = repo.list_as_of(context=context, as_of=now - timedelta(seconds=1))
    assert hidden == []


def test_quarantine_persists_without_observation(
    postgres_database: PostgresDatabase,
) -> None:
    now = datetime(2026, 7, 19, 12, 5, tzinfo=UTC)
    context = _context()
    result = import_fixture(
        context=context,
        fixture_name="evm_block.json",
        now=now,
        provider_quality=ProviderQualityState.CONFLICTED,
    )
    assert result.quarantine is not None
    assert result.observation is None
    repo = ObservationRepository(postgres_database)
    repo.save_envelope(
        envelope=result.envelope,
        payload=loads(result.payload_bytes.decode("utf-8")),
    )
    repo.save_quarantine(quarantine=result.quarantine)
    assert repo.list_as_of(context=context, as_of=now, subject_id="protocol:uniswap") == []


def test_orphan_update_preserves_observation_id(
    postgres_database: PostgresDatabase,
) -> None:
    now = datetime(2026, 7, 19, 12, 10, tzinfo=UTC)
    context = _context()
    result = import_fixture(context=context, fixture_name="bitcoin_block.json", now=now)
    assert result.observation is not None
    repo = ObservationRepository(postgres_database)
    repo.save_envelope(
        envelope=result.envelope,
        payload=loads(result.payload_bytes.decode("utf-8")),
    )
    repo.save_observation(observation=result.observation)
    orphaned = mark_orphaned(result.observation)
    repo.update_observation_quality(observation=orphaned)
    fetched = repo.get_observation(
        context=context,
        observation_id=result.observation.header.observation_id,
    )
    assert fetched is not None
    assert fetched["header"]["quality"] == "orphaned"
