-- Phase 2B append-only canonical document versions and lifecycle events.
-- Parser attempt history remains the retained source; versions never overwrite.

CREATE TABLE atlas_ingestion.canonical_document_versions (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    document_version_id text NOT NULL CHECK (document_version_id ~ '^canonical:[0-9a-f]{64}$'),
    manifest_id uuid NOT NULL,
    acquisition_id uuid NOT NULL,
    parse_attempt_id uuid NOT NULL,
    artifact_id text NOT NULL,
    canonical_artifact_id text NOT NULL,
    canonical_content_hash text NOT NULL CHECK (canonical_content_hash ~ '^[0-9a-f]{64}$'),
    parser_configuration_hash text NOT NULL CHECK (parser_configuration_hash ~ '^[0-9a-f]{64}$'),
    manifest jsonb NOT NULL CHECK (jsonb_typeof(manifest) = 'object'),
    qualification jsonb NOT NULL CHECK (jsonb_typeof(qualification) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, document_version_id),
    UNIQUE (tenant_id, workspace_id, manifest_id),
    FOREIGN KEY (tenant_id, workspace_id, acquisition_id)
        REFERENCES atlas_ingestion.document_acquisitions(tenant_id, workspace_id, acquisition_id),
    FOREIGN KEY (tenant_id, workspace_id, parse_attempt_id)
        REFERENCES atlas_ingestion.document_parser_attempts(tenant_id, workspace_id, attempt_id),
    FOREIGN KEY (tenant_id, workspace_id, artifact_id)
        REFERENCES atlas_core.artifact_references(tenant_id, workspace_id, artifact_id),
    FOREIGN KEY (tenant_id, workspace_id, canonical_artifact_id)
        REFERENCES atlas_core.artifact_references(tenant_id, workspace_id, artifact_id)
);

CREATE INDEX canonical_document_versions_acquisition
ON atlas_ingestion.canonical_document_versions (
    tenant_id, workspace_id, acquisition_id, recorded_at
);

CREATE TABLE atlas_ingestion.canonical_lifecycle_events (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    event_id uuid NOT NULL,
    acquisition_id uuid NOT NULL,
    document_version_id text NOT NULL,
    event_type text NOT NULL CHECK (event_type = 'CanonicalDocumentRecorded'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, event_id),
    UNIQUE (tenant_id, workspace_id, document_version_id, event_type),
    FOREIGN KEY (tenant_id, workspace_id, document_version_id)
        REFERENCES atlas_ingestion.canonical_document_versions(
            tenant_id, workspace_id, document_version_id
        ),
    FOREIGN KEY (tenant_id, workspace_id, acquisition_id)
        REFERENCES atlas_ingestion.document_acquisitions(tenant_id, workspace_id, acquisition_id)
);

CREATE TRIGGER canonical_document_versions_are_append_only
BEFORE UPDATE OR DELETE ON atlas_ingestion.canonical_document_versions
FOR EACH ROW EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER canonical_document_versions_reject_truncate
BEFORE TRUNCATE ON atlas_ingestion.canonical_document_versions
FOR EACH STATEMENT EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER canonical_lifecycle_events_are_append_only
BEFORE UPDATE OR DELETE ON atlas_ingestion.canonical_lifecycle_events
FOR EACH ROW EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER canonical_lifecycle_events_reject_truncate
BEFORE TRUNCATE ON atlas_ingestion.canonical_lifecycle_events
FOR EACH STATEMENT EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();
