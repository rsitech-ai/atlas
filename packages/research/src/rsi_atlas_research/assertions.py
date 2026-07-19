"""Assertion construction from specialist findings."""

from __future__ import annotations

from rsi_atlas_contracts import (
    FindingCompletionStatus,
    ResearchAssertion,
    SpecialistFinding,
    research_assertion_id,
)


class AssertionBuildError(ValueError):
    """Raised when assertion construction fails closed."""


class AssertionBuilder:
    """Build atomic assertions before prose realization."""

    def from_finding(
        self,
        *,
        run_id: str,
        finding: SpecialistFinding,
        subject_ids: tuple[str, ...] = (),
    ) -> ResearchAssertion | None:
        if finding.completion_status in {
            FindingCompletionStatus.INSUFFICIENT_EVIDENCE,
            FindingCompletionStatus.FAILED,
            FindingCompletionStatus.NOT_APPLICABLE,
        }:
            return None
        if not finding.supporting_chunk_ids:
            raise AssertionBuildError("finding lacks supporting chunks for assertion")
        statement = finding.answer.strip()
        if not statement:
            raise AssertionBuildError("empty assertion statement")
        return ResearchAssertion(
            assertion_id=research_assertion_id(
                run_id=run_id,
                finding_id=finding.finding_id,
                statement=statement,
                supporting_chunk_ids=finding.supporting_chunk_ids,
            ),
            run_id=run_id,
            finding_id=finding.finding_id,
            statement=statement,
            subject_ids=subject_ids,
            supporting_chunk_ids=finding.supporting_chunk_ids,
            contradictory_chunk_ids=finding.contradictory_chunk_ids,
            is_interpretation=False,
            confidence=finding.confidence,
        )
