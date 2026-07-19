"""Citation binding from assertions to evidence excerpts."""

from __future__ import annotations

from rsi_atlas_contracts import (
    CitationBinding,
    CitationRole,
    EvidenceItemKind,
    EvidencePacket,
    ResearchAssertion,
    citation_binding_id,
)


class CitationError(ValueError):
    """Raised when citation binding fails closed."""


class CitationBinder:
    """Bind direct_support citations before report rendering."""

    def bind_assertion(
        self,
        *,
        assertion: ResearchAssertion,
        packet: EvidencePacket,
    ) -> tuple[CitationBinding, ...]:
        by_chunk = {item.chunk_id: item for item in packet.items}
        bindings: list[CitationBinding] = []
        for chunk_id in assertion.supporting_chunk_ids:
            item = by_chunk.get(chunk_id)
            if item is None:
                raise CitationError(f"supporting chunk {chunk_id} missing from packet")
            if item.item_kind is not EvidenceItemKind.SOURCE_CONTENT:
                raise CitationError("primary citations require SOURCE_CONTENT")
            bindings.append(
                CitationBinding(
                    citation_id=citation_binding_id(
                        assertion_id=assertion.assertion_id,
                        chunk_id=chunk_id,
                        role=CitationRole.DIRECT_SUPPORT,
                        excerpt_hash=item.excerpt_hash,
                    ),
                    assertion_id=assertion.assertion_id,
                    chunk_id=chunk_id,
                    role=CitationRole.DIRECT_SUPPORT,
                    excerpt_hash=item.excerpt_hash,
                    locator=f"chunk:{chunk_id}:fusion_rank:{item.fusion_rank}",
                    item_kind=EvidenceItemKind.SOURCE_CONTENT,
                )
            )
        if not bindings:
            raise CitationError("assertion produced no citations")
        return tuple(bindings)
