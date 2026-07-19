"""Extractive multi-specialist runners (stdlib; no LangGraph)."""

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

from rsi_atlas_research.document_specialist import SpecialistError

# Keyword bias per specialist — ponytail: ceiling=keyword extractive; upgrade=qualified local LLM.
_SPECIALIST_HINTS: dict[SpecialistType, frozenset[str]] = {
    SpecialistType.TOKENOMICS: frozenset(
        {"supply", "emission", "inflation", "unlock", "vesting", "tokenomics", "circulating"}
    ),
    SpecialistType.MARKET: frozenset(
        {"price", "volume", "liquidity", "spread", "funding", "basis", "market", "orderbook"}
    ),
    SpecialistType.ON_CHAIN: frozenset(
        {"address", "tx", "transaction", "block", "reorg", "finality", "contract", "wallet"}
    ),
    SpecialistType.GOVERNANCE: frozenset(
        {"proposal", "vote", "quorum", "governance", "multisig", "timelock"}
    ),
    SpecialistType.TREASURY: frozenset(
        {"treasury", "reserve", "balance", "runway", "stablecoin", "cash"}
    ),
    SpecialistType.SECURITY: frozenset(
        {"audit", "vulnerability", "exploit", "privilege", "key", "security", "incident"}
    ),
    SpecialistType.CONTRADICTION: frozenset(
        {"however", "contrary", "conflict", "disagree", "inconsistent", "versus"}
    ),
}


class ExtractiveSpecialist:
    """Keyword-biased extractive specialist over an EvidencePacket."""

    def __init__(self, specialist_type: SpecialistType) -> None:
        if specialist_type is SpecialistType.DOCUMENT_EVIDENCE:
            raise SpecialistError("use DocumentEvidenceSpecialist for document_evidence")
        if specialist_type not in _SPECIALIST_HINTS:
            raise SpecialistError(f"specialist {specialist_type.value} remains blocked")
        self._type = specialist_type
        self._hints = _SPECIALIST_HINTS[specialist_type]

    def run(
        self,
        *,
        task: SpecialistTask,
        packet: EvidencePacket,
        now: datetime | None = None,
    ) -> SpecialistFinding:
        recorded_at = now or datetime.now(UTC)
        if task.specialist_type is not self._type:
            raise SpecialistError(f"expected {self._type.value}")
        if task.packet_id != packet.packet_id or task.run_id != packet.run_id:
            raise SpecialistError("task/packet identity mismatch")

        biased = task.subquestion + " " + " ".join(sorted(self._hints)[:6])
        tokens = _tokens(biased)
        scored: list[tuple[int, str, str]] = []
        for item in packet.items:
            preview_tokens = _tokens(item.text_preview)
            overlap = len(tokens.intersection(preview_tokens))
            hint_boost = len(self._hints.intersection(preview_tokens))
            score = overlap + 2 * hint_boost
            if score > 0:
                scored.append((score, item.chunk_id, item.text_preview))
        scored.sort(key=lambda row: (-row[0], row[1]))

        if not scored:
            answer = f"Insufficient {self._type.value} evidence for the subquestion."
            return SpecialistFinding(
                finding_id=specialist_finding_id(
                    task_id=task.task_id,
                    answer=answer,
                    completion_status=FindingCompletionStatus.INSUFFICIENT_EVIDENCE,
                    supporting_chunk_ids=(),
                ),
                task_id=task.task_id,
                specialist_type=self._type,
                answer=answer,
                supporting_chunk_ids=(),
                missing_evidence=(f"no overlapping {self._type.value} passages",),
                completion_status=FindingCompletionStatus.INSUFFICIENT_EVIDENCE,
                confidence=0.1,
                recorded_at=recorded_at,
            )

        best_score, _chunk, best_preview = scored[0]
        supporting = tuple(chunk_id for _, chunk_id, _ in scored[:3])
        answer = best_preview.strip()
        if len(answer) > 500:
            answer = answer[:497] + "..."
        status = (
            FindingCompletionStatus.SUPPORTED
            if best_score >= 3
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
            specialist_type=self._type,
            answer=answer,
            supporting_chunk_ids=supporting,
            uncertainties=() if status is FindingCompletionStatus.SUPPORTED else ("weak overlap",),
            completion_status=status,
            confidence=min(1.0, 0.35 + 0.1 * best_score),
            recorded_at=recorded_at,
        )


def _tokens(text: str) -> set[str]:
    normalized = "".join(ch.lower() if ch.isalnum() else " " for ch in text)
    return {part for part in normalized.split() if len(part) > 2}


__all__ = ["ExtractiveSpecialist", "SpecialistError"]
