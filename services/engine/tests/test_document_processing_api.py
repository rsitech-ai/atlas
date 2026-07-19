from uuid import UUID

from fastapi.testclient import TestClient
from rsi_atlas_contracts import ArtifactCommandContext
from rsi_atlas_engine.api import create_app
from rsi_atlas_ingestion.processing_pipeline import (
    CanonicalPageEvidence,
    ChunkSetEvidence,
    ChunkSetSummary,
    DocumentProcessingStatus,
)


class FakeProcessingService:
    def __init__(self) -> None:
        self.started: list[UUID] = []
        self.chunked: list[str] = []

    def start(
        self, *, context: ArtifactCommandContext, acquisition_id: UUID
    ) -> DocumentProcessingStatus:
        del context
        self.started.append(acquisition_id)
        return DocumentProcessingStatus(
            acquisition_id=acquisition_id,
            state="canonicalized",
            document_version_id="canonical:" + ("a" * 64),
            canonical_content_hash="a" * 64,
            page_count=1,
            warnings=(),
        )

    def status(
        self, *, context: ArtifactCommandContext, acquisition_id: UUID
    ) -> DocumentProcessingStatus:
        del context
        return DocumentProcessingStatus(acquisition_id=acquisition_id, state="idle")

    def page(
        self,
        *,
        context: ArtifactCommandContext,
        document_version_id: str,
        page_number: int,
    ) -> CanonicalPageEvidence:
        del context
        if page_number != 1:
            raise LookupError("page_not_found")
        return CanonicalPageEvidence(
            document_version_id=document_version_id,
            page_number=1,
            raw_text="Hello",
            normalized_text="Hello",
            element_count=1,
            elements=(
                {
                    "kind": "text",
                    "role": "paragraph",
                    "reading_order": 0,
                    "raw_text": "Hello",
                    "normalized_text": "Hello",
                    "source_box": {},
                    "normalized_box": {},
                    "source_span_id": "span_0000",
                    "raw_text_hash": "b" * 64,
                    "normalized_text_hash": "b" * 64,
                },
            ),
            source_artifact_digest="c" * 64,
            canonical_content_hash="a" * 64,
            parser_name="pypdf",
            parser_version="6.14.2",
        )

    def chunk(
        self, *, context: ArtifactCommandContext, document_version_id: str
    ) -> tuple[ChunkSetSummary, ...]:
        self.chunked.append(document_version_id)
        return self.list_chunk_sets(context=context, document_version_id=document_version_id)

    def list_chunk_sets(
        self, *, context: ArtifactCommandContext, document_version_id: str
    ) -> tuple[ChunkSetSummary, ...]:
        del context
        return (
            ChunkSetSummary(
                document_version_id=document_version_id,
                chunk_set_id="chunkset:" + ("d" * 64),
                strategy_id="page_based",
                configuration_hash="e" * 64,
                chunk_set_content_hash="f" * 64,
                chunk_count=2,
                searchable=False,
            ),
        )

    def chunk_set(self, *, context: ArtifactCommandContext, chunk_set_id: str) -> ChunkSetEvidence:
        del context
        if chunk_set_id != "chunkset:" + ("d" * 64):
            raise LookupError("chunk_set_not_found")
        return ChunkSetEvidence(
            document_version_id="canonical:" + ("a" * 64),
            chunk_set_id=chunk_set_id,
            strategy_id="page_based",
            configuration_hash="e" * 64,
            chunk_set_content_hash="f" * 64,
            chunk_count=1,
            searchable=False,
            chunks=(
                {
                    "chunk_id": "chunk:" + ("1" * 64),
                    "ordinal": 0,
                    "text": "Bitcoin",
                    "token_count": 1,
                    "page_numbers": [1],
                    "source_element_ids": ["element:" + ("2" * 64)],
                    "metadata": {"family": "page_based"},
                },
            ),
        )


def _headers(workspace_id: UUID) -> dict[str, str]:
    return {
        "x-rsi-tenant-id": str(UUID("11111111-1111-4111-8111-111111111111")),
        "x-rsi-actor-id": str(UUID("22222222-2222-4222-8222-222222222222")),
        "x-rsi-trace-id": str(UUID("33333333-3333-4333-8333-333333333333")),
        "x-rsi-workspace-check": str(workspace_id),
    }


def test_processing_start_and_page_routes() -> None:
    processing = FakeProcessingService()
    client = TestClient(
        create_app(
            status_factory=lambda: (_ for _ in ()).throw(RuntimeError("unused")),
            document_admission_service=object(),  # type: ignore[arg-type]
            import_staging_area=object(),  # type: ignore[arg-type]
            document_processing_service=processing,
        )
    )
    workspace_id = UUID("44444444-4444-4444-8444-444444444444")
    acquisition_id = UUID("55555555-5555-4555-8555-555555555555")
    headers = _headers(workspace_id)

    started = client.post(
        f"/v1/workspaces/{workspace_id}/acquisitions/{acquisition_id}/processing:start",
        headers=headers,
    )
    assert started.status_code == 200
    body = started.json()
    assert body["state"] == "canonicalized"
    assert body["page_count"] == 1
    assert processing.started == [acquisition_id]

    status = client.get(
        f"/v1/workspaces/{workspace_id}/acquisitions/{acquisition_id}/processing",
        headers=headers,
    )
    assert status.status_code == 200
    assert status.json()["state"] == "idle"

    page = client.get(
        f"/v1/workspaces/{workspace_id}/canonical/canonical:{'a' * 64}/pages/1",
        headers=headers,
    )
    assert page.status_code == 200
    assert page.json()["raw_text"] == "Hello"

    missing = client.get(
        f"/v1/workspaces/{workspace_id}/canonical/canonical:{'a' * 64}/pages/9",
        headers=headers,
    )
    assert missing.status_code == 404


def test_chunk_set_inspect_routes() -> None:
    processing = FakeProcessingService()
    client = TestClient(
        create_app(
            status_factory=lambda: (_ for _ in ()).throw(RuntimeError("unused")),
            document_admission_service=object(),  # type: ignore[arg-type]
            import_staging_area=object(),  # type: ignore[arg-type]
            document_processing_service=processing,
        )
    )
    workspace_id = UUID("44444444-4444-4444-8444-444444444444")
    headers = _headers(workspace_id)
    document_version_id = f"canonical:{'a' * 64}"

    started = client.post(
        f"/v1/workspaces/{workspace_id}/canonical/{document_version_id}/chunking:start",
        headers=headers,
    )
    assert started.status_code == 200
    body = started.json()
    assert len(body) == 1
    assert body[0]["searchable"] is False
    assert body[0]["strategy_id"] == "page_based"
    assert processing.chunked == [document_version_id]

    listed = client.get(
        f"/v1/workspaces/{workspace_id}/canonical/{document_version_id}/chunk-sets",
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json()[0]["chunk_set_id"] == "chunkset:" + ("d" * 64)

    detail = client.get(
        f"/v1/workspaces/{workspace_id}/chunk-sets/chunkset:{'d' * 64}",
        headers=headers,
    )
    assert detail.status_code == 200
    assert detail.json()["chunks"][0]["text"] == "Bitcoin"
    assert detail.json()["searchable"] is False

    missing = client.get(
        f"/v1/workspaces/{workspace_id}/chunk-sets/chunkset:{'0' * 64}",
        headers=headers,
    )
    assert missing.status_code == 404


def test_processing_rejects_invalid_page_bounds() -> None:
    processing = FakeProcessingService()
    client = TestClient(
        create_app(
            status_factory=lambda: (_ for _ in ()).throw(RuntimeError("unused")),
            document_admission_service=object(),  # type: ignore[arg-type]
            import_staging_area=object(),  # type: ignore[arg-type]
            document_processing_service=processing,
        )
    )
    workspace_id = UUID("44444444-4444-4444-8444-444444444444")
    response = client.get(
        f"/v1/workspaces/{workspace_id}/canonical/canonical:{'a' * 64}/pages/0",
        headers=_headers(workspace_id),
    )
    assert response.status_code == 422
