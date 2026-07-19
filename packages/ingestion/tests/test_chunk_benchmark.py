"""Frozen intrinsic chunker benchmark integrity tests."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest
from rsi_atlas_contracts import CanonicalDocument, ChunkStrategyFamily
from rsi_atlas_ingestion.chunking import CHUNK_CONFIGURATION_HASH, chunk_canonical_document

ROOT = Path("packages/ingestion/benchmarks/chunking")
MANIFEST = ROOT / "manifest.json"


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST.read_text())


def test_manifest_pins_configuration_and_five_families(manifest: dict) -> None:
    assert manifest["schema_version"] == "1.0.0"
    assert manifest["partition"] == "development"
    assert manifest["configuration_hash"] == CHUNK_CONFIGURATION_HASH
    families = {entry["family"] for entry in manifest["families"]}
    assert {
        "fixed_token",
        "recursive",
        "page_based",
        "parent_child",
        "table_aware",
    } == families


def test_fixture_hash_matches_committed_bytes(manifest: dict) -> None:
    fixture_path = ROOT / manifest["fixture"]["path"]
    payload = fixture_path.read_bytes()
    assert sha256(payload).hexdigest() == manifest["fixture"]["sha256"]
    document = CanonicalDocument.model_validate_json(payload)
    assert len(document.pages) == manifest["fixture"]["page_count"]
    element_count = sum(len(page.elements) for page in document.pages)
    assert element_count == manifest["fixture"]["element_count"]


@pytest.mark.parametrize(
    "family_name",
    sorted(
        [
            "fixed_token",
            "recursive",
            "page_based",
            "parent_child",
            "table_aware",
        ]
    ),
)
def test_family_matches_frozen_golden(manifest: dict, family_name: str) -> None:
    entry = next(item for item in manifest["families"] if item["family"] == family_name)
    document = CanonicalDocument.model_validate_json(
        (ROOT / manifest["fixture"]["path"]).read_bytes()
    )
    chunk_set = chunk_canonical_document(
        document,
        family=ChunkStrategyFamily(family_name),
        document_version_id=manifest["document_version_id"],
        canonical_content_hash=manifest["canonical_content_hash"],
    )
    golden_bytes = (ROOT / entry["golden_path"]).read_bytes()
    assert sha256(golden_bytes).hexdigest() == entry["golden_sha256"]
    assert chunk_set.canonical_json_bytes() == golden_bytes
    assert chunk_set.chunk_set_id == entry["chunk_set_id"]
    assert chunk_set.content_hash() == entry["content_hash"]
    assert chunk_set.quality.chunk_count == entry["chunk_count"]
    joined = "\n".join(chunk.text for chunk in chunk_set.chunks)
    for token in entry["required_tokens"]:
        assert token in joined
    element_ids = {element.element_id for page in document.pages for element in page.elements}
    for chunk in chunk_set.chunks:
        assert set(chunk.source_element_ids) <= element_ids
