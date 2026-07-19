from __future__ import annotations

from uuid import uuid4

from rsi_atlas_contracts import (
    AdmissionOutcome,
    ArtifactCommandContext,
    ArtifactDescriptor,
    ArtifactID,
)
from rsi_atlas_contracts.document_parsing import DocumentProcessingLifecycle
from rsi_atlas_ingestion.preflight_service import _assessment_from_profile, _bind_preflight_profile


def test_assessment_without_promotion_stays_awaiting_review() -> None:
    context = ArtifactCommandContext(
        tenant_id=uuid4(),
        workspace_id=uuid4(),
        actor_id=uuid4(),
        trace_id=uuid4(),
    )
    artifact = ArtifactDescriptor(
        artifact_id=ArtifactID("sha256:" + "a" * 64),
        digest="a" * 64,
        size_bytes=100,
        media_type="application/pdf",
    )
    evidence = {
        "page_count": 1,
        "pages": [
            {
                "page_number": 1,
                "media_box": {
                    "coordinate_system": "pdf_bottom_left_points",
                    "left": "0.000000",
                    "bottom": "0.000000",
                    "right": "612.000000",
                    "top": "792.000000",
                },
                "crop_box": {
                    "coordinate_system": "pdf_bottom_left_points",
                    "left": "0.000000",
                    "bottom": "0.000000",
                    "right": "612.000000",
                    "top": "792.000000",
                },
                "rotation_degrees": 0,
            }
        ],
        "encryption_password_state": "pass",
        "malformed_structure": "pass",
        "embedded_files": "pass",
        "active_actions": "pass",
        "suspicious_references": "pass",
        "decompression_ratio": "pass",
        "decoded_stream_bytes": 10,
        "character_count": 10,
        "image_only_page_count": 0,
        "warnings": [],
    }
    profile = _bind_preflight_profile(
        context=context,
        acquisition_id=uuid4(),
        artifact=artifact,
        evidence=evidence,
    )
    draft = _assessment_from_profile(
        context=context,
        acquisition_id=profile.acquisition_id,
        artifact=artifact,
        prior_admission_hash="b" * 64,
        profile=profile,
    )
    assert draft.outcome is AdmissionOutcome.QUARANTINE_FOR_REVIEW
    assert draft.lifecycle is DocumentProcessingLifecycle.AWAITING_REVIEW
    assert draft.promotion is None
    assert "promotion_required_before_accept" in draft.reason_codes


def test_encrypted_evidence_requests_password() -> None:
    context = ArtifactCommandContext(
        tenant_id=uuid4(),
        workspace_id=uuid4(),
        actor_id=uuid4(),
        trace_id=uuid4(),
    )
    artifact = ArtifactDescriptor(
        artifact_id=ArtifactID("sha256:" + "c" * 64),
        digest="c" * 64,
        size_bytes=50,
        media_type="application/pdf",
    )
    evidence = {
        "page_count": None,
        "pages": [],
        "encryption_password_state": "fail",
        "malformed_structure": "unknown",
        "embedded_files": "unknown",
        "active_actions": "unknown",
        "suspicious_references": "unknown",
        "decompression_ratio": "unknown",
        "decoded_stream_bytes": 0,
        "character_count": 0,
        "image_only_page_count": None,
        "warnings": ["password_required_or_encrypted"],
    }
    profile = _bind_preflight_profile(
        context=context,
        acquisition_id=uuid4(),
        artifact=artifact,
        evidence=evidence,
    )
    draft = _assessment_from_profile(
        context=context,
        acquisition_id=profile.acquisition_id,
        artifact=artifact,
        prior_admission_hash="d" * 64,
        profile=profile,
    )
    assert draft.outcome is AdmissionOutcome.REQUEST_PASSWORD
    assert draft.lifecycle is DocumentProcessingLifecycle.AWAITING_PASSWORD
