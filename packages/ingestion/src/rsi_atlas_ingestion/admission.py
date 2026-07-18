from dataclasses import dataclass
from uuid import UUID

from rsi_atlas_contracts import (
    AcquisitionRequest,
    AdmissionOutcome,
    DocumentLifecycle,
    PDFSafetyProfile,
    SafetyCheckState,
)


@dataclass(frozen=True, slots=True)
class PDFAdmissionDecision:
    lifecycle: DocumentLifecycle
    outcome: AdmissionOutcome
    reason_codes: tuple[str, ...]
    duplicate_of_acquisition_id: UUID | None = None

    def __post_init__(self) -> None:
        expected_lifecycle = {
            AdmissionOutcome.QUARANTINE_FOR_REVIEW: DocumentLifecycle.AWAITING_REVIEW,
            AdmissionOutcome.REQUEST_PASSWORD: DocumentLifecycle.AWAITING_PASSWORD,
            AdmissionOutcome.REJECT_POLICY_VIOLATION: DocumentLifecycle.REJECTED,
            AdmissionOutcome.REJECT_UNSAFE: DocumentLifecycle.REJECTED,
            AdmissionOutcome.MARK_EXACT_DUPLICATE: DocumentLifecycle.DUPLICATE,
        }.get(self.outcome)
        if expected_lifecycle is None or self.lifecycle is not expected_lifecycle:
            raise ValueError("PDF admission decision is not valid for Phase 2A")
        if not self.reason_codes or tuple(sorted(set(self.reason_codes))) != self.reason_codes:
            raise ValueError("PDF admission reason codes must be nonempty, unique, and sorted")
        is_duplicate = self.outcome is AdmissionOutcome.MARK_EXACT_DUPLICATE
        if is_duplicate != (self.duplicate_of_acquisition_id is not None):
            raise ValueError("exact duplicate decision and target must appear together")


class PDFAdmissionPolicy:
    def evaluate(
        self,
        *,
        profile: PDFSafetyProfile,
        request: AcquisitionRequest,
        duplicate_of_acquisition_id: UUID | None,
    ) -> PDFAdmissionDecision:
        checked_profile = PDFSafetyProfile.model_validate(profile)
        checked_request = AcquisitionRequest.model_validate(request)

        if duplicate_of_acquisition_id is not None:
            if not isinstance(duplicate_of_acquisition_id, UUID):
                raise TypeError("duplicate acquisition identity must be a UUID")
            if duplicate_of_acquisition_id == checked_request.acquisition_id:
                raise ValueError("an acquisition cannot duplicate itself")
            return _decision(
                lifecycle=DocumentLifecycle.DUPLICATE,
                outcome=AdmissionOutcome.MARK_EXACT_DUPLICATE,
                reasons=("exact_duplicate",),
                duplicate_of_acquisition_id=duplicate_of_acquisition_id,
            )

        if checked_profile.mime_signature_consistency is SafetyCheckState.FAIL:
            return _decision(
                lifecycle=DocumentLifecycle.REJECTED,
                outcome=AdmissionOutcome.REJECT_UNSAFE,
                reasons=("pdf_signature_or_mime_invalid",),
            )

        policy_reasons = _failed_reasons(
            checked_profile,
            (
                ("size_limit", "size_limit_exceeded"),
                ("source_policy", "source_policy_denied"),
            ),
        )
        if policy_reasons:
            return _decision(
                lifecycle=DocumentLifecycle.REJECTED,
                outcome=AdmissionOutcome.REJECT_POLICY_VIOLATION,
                reasons=policy_reasons,
            )

        if checked_profile.encryption_password_state is SafetyCheckState.FAIL:
            return _decision(
                lifecycle=DocumentLifecycle.AWAITING_PASSWORD,
                outcome=AdmissionOutcome.REQUEST_PASSWORD,
                reasons=("password_required",),
            )

        review_reasons = _failed_reasons(
            checked_profile,
            (
                ("active_actions", "active_actions_detected"),
                ("available_disk", "available_disk_insufficient"),
                ("decompression_ratio", "decompression_ratio_unsafe"),
                ("embedded_files", "embedded_files_detected"),
                ("malformed_structure", "malformed_structure"),
                ("page_count_limit", "page_count_limit_exceeded"),
                ("suspicious_references", "suspicious_references_detected"),
            ),
        )
        if review_reasons:
            return _decision(
                lifecycle=DocumentLifecycle.AWAITING_REVIEW,
                outcome=AdmissionOutcome.QUARANTINE_FOR_REVIEW,
                reasons=review_reasons,
            )

        if SafetyCheckState.UNKNOWN in _mandatory_check_states(checked_profile):
            return _decision(
                lifecycle=DocumentLifecycle.AWAITING_REVIEW,
                outcome=AdmissionOutcome.QUARANTINE_FOR_REVIEW,
                reasons=("required_check_unknown",),
            )

        return _decision(
            lifecycle=DocumentLifecycle.AWAITING_REVIEW,
            outcome=AdmissionOutcome.QUARANTINE_FOR_REVIEW,
            reasons=("isolated_profiler_not_promoted",),
        )


def _failed_reasons(
    profile: PDFSafetyProfile,
    checks: tuple[tuple[str, str], ...],
) -> tuple[str, ...]:
    return tuple(
        sorted(
            reason
            for field_name, reason in checks
            if getattr(profile, field_name) is SafetyCheckState.FAIL
        )
    )


def _mandatory_check_states(profile: PDFSafetyProfile) -> tuple[SafetyCheckState, ...]:
    return (
        profile.mime_signature_consistency,
        profile.size_limit,
        profile.page_count_limit,
        profile.encryption_password_state,
        profile.malformed_structure,
        profile.embedded_files,
        profile.active_actions,
        profile.suspicious_references,
        profile.decompression_ratio,
        profile.source_policy,
        profile.available_disk,
    )


def _decision(
    *,
    lifecycle: DocumentLifecycle,
    outcome: AdmissionOutcome,
    reasons: tuple[str, ...],
    duplicate_of_acquisition_id: UUID | None = None,
) -> PDFAdmissionDecision:
    return PDFAdmissionDecision(
        lifecycle=lifecycle,
        outcome=outcome,
        reason_codes=tuple(sorted(set(reasons))),
        duplicate_of_acquisition_id=duplicate_of_acquisition_id,
    )
