"""Deterministic Document Evidence specialist (no LLM in this slice)."""

from __future__ import annotations

from datetime import UTC, datetime

from rsi_atlas_contracts import (
    EvidencePacket,
    FindingCompletionStatus,
    SpecialistFinding,
    SpecialistTask,
    SpecialistType,
    specialist_finding_id,
)


class SpecialistError(ValueError):
    """Raised when specialist execution fails closed."""


class DocumentEvidenceSpecialist:
    """Extractive specialist over an EvidencePacket.

    ponytail: ceiling=keyword overlap extractive (not semantic LLM);
    upgrade=qualified local reasoning model under ModelArtifact policy.
    """

    def run(
        self,
        *,
        task: SpecialistTask,
        packet: EvidencePacket,
        now: datetime | None = None,
    ) -> SpecialistFinding:
        recorded_at = now or datetime.now(UTC)
        if task.specialist_type is not SpecialistType.DOCUMENT_EVIDENCE:
            raise SpecialistError("only document_evidence is enabled")
        if task.packet_id != packet.packet_id:
            raise SpecialistError("task packet_id does not match packet")
        if task.run_id != packet.run_id:
            raise SpecialistError("task run_id does not match packet")

        tokens = _tokens(task.subquestion)
        scored: list[tuple[int, str, str]] = []
        for item in packet.items:
            overlap = len(tokens.intersection(_tokens(item.text_preview)))
            if overlap > 0:
                scored.append((overlap, item.chunk_id, item.text_preview))
        scored.sort(key=lambda row: (-row[0], row[1]))

        if not scored:
            answer = "Insufficient document evidence for the subquestion."
            return SpecialistFinding(
                finding_id=specialist_finding_id(
                    task_id=task.task_id,
                    answer=answer,
                    completion_status=FindingCompletionStatus.INSUFFICIENT_EVIDENCE,
                    supporting_chunk_ids=(),
                ),
                task_id=task.task_id,
                specialist_type=SpecialistType.DOCUMENT_EVIDENCE,
                answer=answer,
                supporting_chunk_ids=(),
                missing_evidence=("no overlapping document passages",),
                completion_status=FindingCompletionStatus.INSUFFICIENT_EVIDENCE,
                confidence=0.1,
                recorded_at=recorded_at,
            )

        best_overlap, _best_chunk, best_preview = scored[0]
        supporting = tuple(chunk_id for _, chunk_id, _ in scored[:3])
        answer = best_preview.strip()
        if len(answer) > 500:
            answer = answer[:497] + "..."
        status = (
            FindingCompletionStatus.SUPPORTED
            if best_overlap >= 2
            else FindingCompletionStatus.PARTIALLY_SUPPORTED
        )
        return SpecialistFinding(
            finding_id=specialist_finding_id(
                task_id=task.task_id,
                answer=answer,
                completion_status=status,
                supporting_chunk_ids=supporting,
            ),
            task_id=task.task_id,
            specialist_type=SpecialistType.DOCUMENT_EVIDENCE,
            answer=answer,
            supporting_chunk_ids=supporting,
            uncertainties=() if status is FindingCompletionStatus.SUPPORTED else ("weak overlap",),
            completion_status=status,
            confidence=min(1.0, 0.4 + 0.15 * best_overlap),
            recorded_at=recorded_at,
        )


def _tokens(text: str) -> set[str]:
    normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return {part for part in normalized.split() if len(part) > 2}
