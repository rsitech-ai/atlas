"""Deterministic coverage matrix for development document retrieval."""

from __future__ import annotations

from rsi_atlas_contracts import (
    CoverageCell,
    CoverageStatus,
    FusedEvidenceItem,
    QueryFamily,
    RetrievalDataPlane,
)


def evaluate_coverage(
    *,
    query_family: QueryFamily,
    items: tuple[FusedEvidenceItem, ...],
    required_document_count: int = 1,
) -> tuple[CoverageCell, ...]:
    """Return coverage cells; missing primary evidence blocks material packets."""
    cells: list[CoverageCell] = []
    if not items:
        cells.append(
            CoverageCell(
                requirement_id="primary_document_evidence",
                status=CoverageStatus.MISSING,
                detail="no fused candidates from active publications",
            )
        )
    else:
        document_ids = {item.document_version_id for item in items}
        if len(document_ids) >= required_document_count:
            cells.append(
                CoverageCell(
                    requirement_id="primary_document_evidence",
                    status=CoverageStatus.SATISFIED,
                    detail=f"{len(items)} fused items across {len(document_ids)} documents",
                )
            )
        else:
            cells.append(
                CoverageCell(
                    requirement_id="primary_document_evidence",
                    status=CoverageStatus.PARTIALLY_SATISFIED,
                    detail="fewer documents than required",
                )
            )

    if query_family is QueryFamily.EXACT_LOOKUP:
        exact_hits = [
            item
            for item in items
            if any(
                rank.data_plane is RetrievalDataPlane.EXACT_IDENTIFIER
                for rank in item.component_ranks
            )
        ]
        cells.append(
            CoverageCell(
                requirement_id="exact_identifier_hit",
                status=CoverageStatus.SATISFIED if exact_hits else CoverageStatus.MISSING,
                detail=(
                    f"{len(exact_hits)} exact identifier components"
                    if exact_hits
                    else "no exact identifier hits"
                ),
            )
        )
    else:
        cells.append(
            CoverageCell(
                requirement_id="exact_identifier_hit",
                status=CoverageStatus.NOT_APPLICABLE,
                detail="exact lookup not required for this query family",
            )
        )
    return tuple(cells)


def should_abstain(coverage: tuple[CoverageCell, ...]) -> bool:
    for cell in coverage:
        if (
            cell.requirement_id == "primary_document_evidence"
            and cell.status is CoverageStatus.MISSING
        ):
            return True
        if (
            cell.requirement_id == "exact_identifier_hit"
            and cell.status is CoverageStatus.MISSING
        ):
            return True
    return False
