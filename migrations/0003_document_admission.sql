CREATE SCHEMA IF NOT EXISTS atlas_ingestion;

CREATE TABLE atlas_ingestion.document_acquisitions (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    acquisition_id uuid NOT NULL,
    artifact_id text NOT NULL REFERENCES atlas_core.artifact_contents(artifact_id),
    actor_id uuid NOT NULL,
    trace_id uuid NOT NULL,
    request jsonb NOT NULL CHECK (jsonb_typeof(request) = 'object'),
    profile jsonb NOT NULL CHECK (jsonb_typeof(profile) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, acquisition_id),
    FOREIGN KEY (tenant_id, workspace_id)
        REFERENCES atlas_core.workspaces(tenant_id, id),
    FOREIGN KEY (tenant_id, actor_id)
        REFERENCES atlas_core.actors(tenant_id, id),
    FOREIGN KEY (tenant_id, workspace_id, artifact_id)
        REFERENCES atlas_core.artifact_references(tenant_id, workspace_id, artifact_id)
);

CREATE INDEX document_acquisitions_workspace_artifact
ON atlas_ingestion.document_acquisitions (tenant_id, workspace_id, artifact_id, recorded_at);

CREATE TABLE atlas_ingestion.document_admission_decisions (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    acquisition_id uuid NOT NULL,
    lifecycle text NOT NULL CHECK (
        lifecycle IN ('awaiting_review', 'awaiting_password', 'rejected', 'duplicate')
    ),
    outcome text NOT NULL CHECK (
        outcome IN (
            'request_password',
            'quarantine_for_review',
            'reject_policy_violation',
            'reject_unsafe',
            'mark_exact_duplicate'
        )
    ),
    reason_codes jsonb NOT NULL CHECK (
        jsonb_typeof(reason_codes) = 'array' AND jsonb_array_length(reason_codes) > 0
    ),
    duplicate_of_acquisition_id uuid,
    record jsonb NOT NULL CHECK (jsonb_typeof(record) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, acquisition_id),
    FOREIGN KEY (tenant_id, workspace_id, acquisition_id)
        REFERENCES atlas_ingestion.document_acquisitions(tenant_id, workspace_id, acquisition_id),
    CHECK (
        (outcome = 'mark_exact_duplicate') = (duplicate_of_acquisition_id IS NOT NULL)
    )
);

CREATE TABLE atlas_ingestion.document_duplicate_links (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    acquisition_id uuid NOT NULL,
    duplicate_of_acquisition_id uuid NOT NULL,
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, acquisition_id),
    FOREIGN KEY (tenant_id, workspace_id, acquisition_id)
        REFERENCES atlas_ingestion.document_acquisitions(tenant_id, workspace_id, acquisition_id),
    FOREIGN KEY (tenant_id, workspace_id, duplicate_of_acquisition_id)
        REFERENCES atlas_ingestion.document_acquisitions(tenant_id, workspace_id, acquisition_id),
    CHECK (acquisition_id <> duplicate_of_acquisition_id)
);

CREATE TABLE atlas_ingestion.outbox_events (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    event_id uuid NOT NULL,
    acquisition_id uuid NOT NULL,
    event_type text NOT NULL CHECK (event_type = 'DocumentAdmissionRecorded'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, event_id),
    UNIQUE (tenant_id, workspace_id, acquisition_id, event_type),
    FOREIGN KEY (tenant_id, workspace_id, acquisition_id)
        REFERENCES atlas_ingestion.document_acquisitions(tenant_id, workspace_id, acquisition_id)
);

CREATE OR REPLACE FUNCTION atlas_ingestion.reject_evidence_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'document admission evidence is append-only'
        USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER document_acquisitions_are_append_only
BEFORE UPDATE OR DELETE ON atlas_ingestion.document_acquisitions
FOR EACH ROW EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER document_acquisitions_reject_truncate
BEFORE TRUNCATE ON atlas_ingestion.document_acquisitions
FOR EACH STATEMENT EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER document_admission_decisions_are_append_only
BEFORE UPDATE OR DELETE ON atlas_ingestion.document_admission_decisions
FOR EACH ROW EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER document_admission_decisions_reject_truncate
BEFORE TRUNCATE ON atlas_ingestion.document_admission_decisions
FOR EACH STATEMENT EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER document_duplicate_links_are_append_only
BEFORE UPDATE OR DELETE ON atlas_ingestion.document_duplicate_links
FOR EACH ROW EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER document_duplicate_links_reject_truncate
BEFORE TRUNCATE ON atlas_ingestion.document_duplicate_links
FOR EACH STATEMENT EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER outbox_events_are_append_only
BEFORE UPDATE OR DELETE ON atlas_ingestion.outbox_events
FOR EACH ROW EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER outbox_events_reject_truncate
BEFORE TRUNCATE ON atlas_ingestion.outbox_events
FOR EACH STATEMENT EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();
