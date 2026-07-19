-- Phase 2C append-only chunk set versions. Canonical versions remain immutable.

CREATE TABLE atlas_ingestion.chunk_set_versions (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    chunk_set_id text NOT NULL CHECK (chunk_set_id ~ '^chunkset:[0-9a-f]{64}$'),
    manifest_id uuid NOT NULL,
    acquisition_id uuid NOT NULL,
    document_version_id text NOT NULL,
    strategy_id text NOT NULL CHECK (strategy_id ~ '^[a-z][a-z0-9_]{0,63}$'),
    configuration_hash text NOT NULL CHECK (configuration_hash ~ '^[0-9a-f]{64}$'),
    chunk_set_content_hash text NOT NULL CHECK (chunk_set_content_hash ~ '^[0-9a-f]{64}$'),
    chunk_set_artifact_id text NOT NULL,
    manifest jsonb NOT NULL CHECK (jsonb_typeof(manifest) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, chunk_set_id),
    UNIQUE (tenant_id, workspace_id, manifest_id),
    UNIQUE (
        tenant_id,
        workspace_id,
        document_version_id,
        strategy_id,
        configuration_hash
    ),
    FOREIGN KEY (tenant_id, workspace_id, acquisition_id)
        REFERENCES atlas_ingestion.document_acquisitions(tenant_id, workspace_id, acquisition_id),
    FOREIGN KEY (tenant_id, workspace_id, document_version_id)
        REFERENCES atlas_ingestion.canonical_document_versions(
            tenant_id, workspace_id, document_version_id
        ),
    FOREIGN KEY (tenant_id, workspace_id, chunk_set_artifact_id)
        REFERENCES atlas_core.artifact_references(tenant_id, workspace_id, artifact_id)
);

CREATE INDEX chunk_set_versions_document
ON atlas_ingestion.chunk_set_versions (
    tenant_id, workspace_id, document_version_id, recorded_at
);

CREATE TABLE atlas_ingestion.chunk_set_lifecycle_events (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    event_id uuid NOT NULL,
    acquisition_id uuid NOT NULL,
    chunk_set_id text NOT NULL,
    event_type text NOT NULL CHECK (event_type = 'ChunkSetRecorded'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, event_id),
    UNIQUE (tenant_id, workspace_id, chunk_set_id, event_type),
    FOREIGN KEY (tenant_id, workspace_id, chunk_set_id)
        REFERENCES atlas_ingestion.chunk_set_versions(tenant_id, workspace_id, chunk_set_id),
    FOREIGN KEY (tenant_id, workspace_id, acquisition_id)
        REFERENCES atlas_ingestion.document_acquisitions(tenant_id, workspace_id, acquisition_id)
);

CREATE TRIGGER chunk_set_versions_are_append_only
BEFORE UPDATE OR DELETE ON atlas_ingestion.chunk_set_versions
FOR EACH ROW EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER chunk_set_versions_reject_truncate
BEFORE TRUNCATE ON atlas_ingestion.chunk_set_versions
FOR EACH STATEMENT EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER chunk_set_lifecycle_events_are_append_only
BEFORE UPDATE OR DELETE ON atlas_ingestion.chunk_set_lifecycle_events
FOR EACH ROW EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER chunk_set_lifecycle_events_reject_truncate
BEFORE TRUNCATE ON atlas_ingestion.chunk_set_lifecycle_events
FOR EACH STATEMENT EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();
