-- Phase 2D staging dense/lexical indexes + atomic retrieval publication.
-- Chunk sets remain immutable. Searchable only via document_retrieval_active.

CREATE TABLE atlas_ingestion.retrieval_index_versions (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    index_version_id uuid NOT NULL,
    acquisition_id uuid NOT NULL,
    document_version_id text NOT NULL,
    chunk_set_id text NOT NULL,
    chunk_set_content_hash text NOT NULL CHECK (chunk_set_content_hash ~ '^[0-9a-f]{64}$'),
    embedding_model_id text NOT NULL,
    embedding_configuration_hash text NOT NULL CHECK (embedding_configuration_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL CHECK (status IN ('staging', 'active', 'superseded', 'failed')),
    dense_cardinality integer NOT NULL CHECK (dense_cardinality >= 1),
    lexical_cardinality integer NOT NULL CHECK (lexical_cardinality >= 1),
    exact_identifier_cardinality integer NOT NULL CHECK (exact_identifier_cardinality >= 0),
    dense_content_hash text NOT NULL CHECK (dense_content_hash ~ '^[0-9a-f]{64}$'),
    lexical_content_hash text NOT NULL CHECK (lexical_content_hash ~ '^[0-9a-f]{64}$'),
    exact_content_hash text NOT NULL CHECK (exact_content_hash ~ '^[0-9a-f]{64}$'),
    dense_index_artifact_id text NOT NULL,
    lexical_index_artifact_id text NOT NULL,
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, index_version_id),
    UNIQUE (
        tenant_id,
        workspace_id,
        chunk_set_id,
        embedding_configuration_hash,
        dense_content_hash,
        lexical_content_hash
    ),
    FOREIGN KEY (tenant_id, workspace_id, acquisition_id)
        REFERENCES atlas_ingestion.document_acquisitions(tenant_id, workspace_id, acquisition_id),
    FOREIGN KEY (tenant_id, workspace_id, chunk_set_id)
        REFERENCES atlas_ingestion.chunk_set_versions(tenant_id, workspace_id, chunk_set_id),
    FOREIGN KEY (tenant_id, workspace_id, dense_index_artifact_id)
        REFERENCES atlas_core.artifact_references(tenant_id, workspace_id, artifact_id),
    FOREIGN KEY (tenant_id, workspace_id, lexical_index_artifact_id)
        REFERENCES atlas_core.artifact_references(tenant_id, workspace_id, artifact_id)
);

CREATE INDEX retrieval_index_versions_chunk_set
ON atlas_ingestion.retrieval_index_versions (
    tenant_id, workspace_id, chunk_set_id, recorded_at
);

CREATE TABLE atlas_ingestion.dense_chunk_embeddings (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    index_version_id uuid NOT NULL,
    chunk_id text NOT NULL CHECK (chunk_id ~ '^chunk:[0-9a-f]{64}$'),
    chunk_text_hash text NOT NULL CHECK (chunk_text_hash ~ '^[0-9a-f]{64}$'),
    embedding vector(64) NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (tenant_id, workspace_id, index_version_id, chunk_id),
    UNIQUE (tenant_id, workspace_id, index_version_id, ordinal),
    FOREIGN KEY (tenant_id, workspace_id, index_version_id)
        REFERENCES atlas_ingestion.retrieval_index_versions(
            tenant_id, workspace_id, index_version_id
        )
);

CREATE TABLE atlas_ingestion.lexical_chunk_documents (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    index_version_id uuid NOT NULL,
    chunk_id text NOT NULL CHECK (chunk_id ~ '^chunk:[0-9a-f]{64}$'),
    chunk_text_hash text NOT NULL CHECK (chunk_text_hash ~ '^[0-9a-f]{64}$'),
    body text NOT NULL CHECK (length(body) > 0),
    tsv tsvector NOT NULL,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (tenant_id, workspace_id, index_version_id, chunk_id),
    UNIQUE (tenant_id, workspace_id, index_version_id, ordinal),
    FOREIGN KEY (tenant_id, workspace_id, index_version_id)
        REFERENCES atlas_ingestion.retrieval_index_versions(
            tenant_id, workspace_id, index_version_id
        )
);

CREATE INDEX lexical_chunk_documents_tsv
ON atlas_ingestion.lexical_chunk_documents
USING GIN (tsv);

CREATE TABLE atlas_ingestion.exact_identifier_hits (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    index_version_id uuid NOT NULL,
    chunk_id text NOT NULL CHECK (chunk_id ~ '^chunk:[0-9a-f]{64}$'),
    identifier_kind text NOT NULL CHECK (identifier_kind ~ '^[a-z][a-z0-9_]{0,63}$'),
    identifier_value text NOT NULL CHECK (length(identifier_value) > 0),
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (
        tenant_id, workspace_id, index_version_id, chunk_id, identifier_kind, identifier_value
    ),
    FOREIGN KEY (tenant_id, workspace_id, index_version_id)
        REFERENCES atlas_ingestion.retrieval_index_versions(
            tenant_id, workspace_id, index_version_id
        )
);

CREATE TABLE atlas_ingestion.retrieval_publication_manifests (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    publication_id text NOT NULL CHECK (publication_id ~ '^publication:[0-9a-f]{64}$'),
    manifest_id uuid NOT NULL,
    index_version_id uuid NOT NULL,
    acquisition_id uuid NOT NULL,
    document_version_id text NOT NULL,
    chunk_set_id text NOT NULL,
    lifecycle text NOT NULL CHECK (lifecycle IN ('index_validated', 'published')),
    searchable boolean NOT NULL,
    manifest jsonb NOT NULL CHECK (jsonb_typeof(manifest) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, publication_id, lifecycle),
    UNIQUE (tenant_id, workspace_id, manifest_id),
    UNIQUE (tenant_id, workspace_id, index_version_id, lifecycle),
    FOREIGN KEY (tenant_id, workspace_id, index_version_id)
        REFERENCES atlas_ingestion.retrieval_index_versions(
            tenant_id, workspace_id, index_version_id
        ),
    FOREIGN KEY (tenant_id, workspace_id, acquisition_id)
        REFERENCES atlas_ingestion.document_acquisitions(tenant_id, workspace_id, acquisition_id),
    CHECK (
        (lifecycle = 'index_validated' AND searchable = false)
        OR (lifecycle = 'published' AND searchable = true)
    )
);

CREATE TABLE atlas_ingestion.document_retrieval_active (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    document_version_id text NOT NULL,
    chunk_set_id text NOT NULL,
    index_version_id uuid NOT NULL,
    publication_id text NOT NULL CHECK (publication_id ~ '^publication:[0-9a-f]{64}$'),
    activated_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, document_version_id, chunk_set_id),
    FOREIGN KEY (tenant_id, workspace_id, index_version_id)
        REFERENCES atlas_ingestion.retrieval_index_versions(
            tenant_id, workspace_id, index_version_id
        )
);

CREATE TABLE atlas_ingestion.retrieval_lifecycle_events (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    event_id uuid NOT NULL,
    acquisition_id uuid NOT NULL,
    index_version_id uuid NOT NULL,
    event_type text NOT NULL CHECK (
        event_type IN ('IndexVersionStaged', 'DocumentPublished', 'DocumentSuperseded')
    ),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, event_id),
    FOREIGN KEY (tenant_id, workspace_id, index_version_id)
        REFERENCES atlas_ingestion.retrieval_index_versions(
            tenant_id, workspace_id, index_version_id
        ),
    FOREIGN KEY (tenant_id, workspace_id, acquisition_id)
        REFERENCES atlas_ingestion.document_acquisitions(tenant_id, workspace_id, acquisition_id)
);

CREATE TRIGGER retrieval_index_versions_reject_delete
BEFORE DELETE ON atlas_ingestion.retrieval_index_versions
FOR EACH ROW EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER retrieval_index_versions_reject_truncate
BEFORE TRUNCATE ON atlas_ingestion.retrieval_index_versions
FOR EACH STATEMENT EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER dense_chunk_embeddings_are_append_only
BEFORE UPDATE OR DELETE ON atlas_ingestion.dense_chunk_embeddings
FOR EACH ROW EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER dense_chunk_embeddings_reject_truncate
BEFORE TRUNCATE ON atlas_ingestion.dense_chunk_embeddings
FOR EACH STATEMENT EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER lexical_chunk_documents_are_append_only
BEFORE UPDATE OR DELETE ON atlas_ingestion.lexical_chunk_documents
FOR EACH ROW EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER lexical_chunk_documents_reject_truncate
BEFORE TRUNCATE ON atlas_ingestion.lexical_chunk_documents
FOR EACH STATEMENT EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER exact_identifier_hits_are_append_only
BEFORE UPDATE OR DELETE ON atlas_ingestion.exact_identifier_hits
FOR EACH ROW EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER exact_identifier_hits_reject_truncate
BEFORE TRUNCATE ON atlas_ingestion.exact_identifier_hits
FOR EACH STATEMENT EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER retrieval_publication_manifests_are_append_only
BEFORE UPDATE OR DELETE ON atlas_ingestion.retrieval_publication_manifests
FOR EACH ROW EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER retrieval_publication_manifests_reject_truncate
BEFORE TRUNCATE ON atlas_ingestion.retrieval_publication_manifests
FOR EACH STATEMENT EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER retrieval_lifecycle_events_are_append_only
BEFORE UPDATE OR DELETE ON atlas_ingestion.retrieval_lifecycle_events
FOR EACH ROW EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER retrieval_lifecycle_events_reject_truncate
BEFORE TRUNCATE ON atlas_ingestion.retrieval_lifecycle_events
FOR EACH STATEMENT EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

-- document_retrieval_active is intentionally mutable (atomic pointer flip only).
-- retrieval_index_versions.status may transition staging→active|failed and active→superseded.
