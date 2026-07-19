"""Report draft gate and immutable review decisions."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from rsi_atlas_contracts import (
    ArtifactCommandContext,
    CitationBinding,
    ReportDraft,
    ReportPublicationOutcome,
    ReportSection,
    ResearchAssertion,
    ReviewAction,
    ReviewDecision,
    report_draft_id,
)


class ReportGateError(ValueError):
    """Raised when report drafting fails closed."""


class ReportGate:
    """Assemble a versioned draft only when citations cover assertions."""

    def draft(
        self,
        *,
        context: ArtifactCommandContext,
        run_id: str,
        title: str,
        assertions: tuple[ResearchAssertion, ...],
        citations: tuple[CitationBinding, ...],
        prose: str,
        version: int = 1,
        now: datetime | None = None,
    ) -> ReportDraft:
        recorded_at = now or datetime.now(UTC)
        if not assertions:
            raise ReportGateError("report requires at least one assertion")
        if not citations:
            raise ReportGateError("report requires citations")
        assertion_ids = tuple(item.assertion_id for item in assertions)
        section = ReportSection(
            section_id="findings",
            title="Findings",
            prose=prose.strip() or assertions[0].statement,
            assertion_ids=assertion_ids,
        )
        report_id = report_draft_id(
            run_id=run_id,
            title=title,
            version=version,
            assertions=assertions,
            citations=citations,
        )
        return ReportDraft(
            report_id=report_id,
            run_id=run_id,
            context=context,
            title=title,
            sections=(section,),
            assertions=assertions,
            citations=citations,
            outcome=ReportPublicationOutcome.AWAIT_ANALYST_REVIEW,
            version=version,
            recorded_at=recorded_at,
        )

    def review(
        self,
        *,
        context: ArtifactCommandContext,
        report: ReportDraft,
        action: ReviewAction,
        rationale: str,
        now: datetime | None = None,
    ) -> ReviewDecision:
        recorded_at = now or datetime.now(UTC)
        if action is ReviewAction.APPROVE and report.outcome is ReportPublicationOutcome.REJECTED:
            raise ReportGateError("cannot approve a rejected draft without supersession")
        return ReviewDecision(
            decision_id=uuid4(),
            report_id=report.report_id,
            context=context,
            action=action,
            rationale=rationale.strip(),
            recorded_at=recorded_at,
        )
