ALTER TABLE atlas_ingestion.document_admission_decisions
ADD CONSTRAINT document_admission_outcome_matches_lifecycle CHECK (
    (outcome = 'quarantine_for_review' AND lifecycle = 'awaiting_review')
    OR (outcome = 'request_password' AND lifecycle = 'awaiting_password')
    OR (
        outcome IN ('reject_policy_violation', 'reject_unsafe')
        AND lifecycle = 'rejected'
    )
    OR (outcome = 'mark_exact_duplicate' AND lifecycle = 'duplicate')
);

ALTER TABLE atlas_ingestion.document_admission_decisions
ADD CONSTRAINT document_admission_duplicate_target_exists FOREIGN KEY (
    tenant_id,
    workspace_id,
    duplicate_of_acquisition_id
) REFERENCES atlas_ingestion.document_acquisitions (
    tenant_id,
    workspace_id,
    acquisition_id
);
