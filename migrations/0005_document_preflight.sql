-- Phase 2B append-only document processing attempt journal and assessments.
-- Initial Phase 2A admission rows remain immutable and are never updated here.

CREATE TABLE atlas_ingestion.document_parser_attempts (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    attempt_id uuid NOT NULL,
    acquisition_id uuid NOT NULL,
    artifact_id text NOT NULL,
    operation text NOT NULL CHECK (operation IN ('preflight', 'parse')),
    configuration_hash text NOT NULL CHECK (configuration_hash ~ '^[0-9a-f]{64}$'),
    input_binding_hash text NOT NULL CHECK (input_binding_hash ~ '^[0-9a-f]{64}$'),
    actor_id uuid NOT NULL,
    trace_id uuid NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, attempt_id),
    FOREIGN KEY (tenant_id, workspace_id, acquisition_id)
        REFERENCES atlas_ingestion.document_acquisitions(tenant_id, workspace_id, acquisition_id),
    FOREIGN KEY (tenant_id, workspace_id)
        REFERENCES atlas_core.workspaces(tenant_id, id),
    FOREIGN KEY (tenant_id, actor_id)
        REFERENCES atlas_core.actors(tenant_id, id)
);

CREATE INDEX document_parser_attempts_acquisition
ON atlas_ingestion.document_parser_attempts (tenant_id, workspace_id, acquisition_id, created_at);

CREATE TABLE atlas_ingestion.document_parser_attempt_events (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    attempt_id uuid NOT NULL,
    event_id uuid NOT NULL,
    event_kind text NOT NULL CHECK (
        event_kind IN (
            'started',
            'succeeded',
            'failed',
            'timed_out',
            'killed',
            'cancelled',
            'invalid_output',
            'abandoned'
        )
    ),
    is_terminal boolean NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, attempt_id, event_id),
    FOREIGN KEY (tenant_id, workspace_id, attempt_id)
        REFERENCES atlas_ingestion.document_parser_attempts(tenant_id, workspace_id, attempt_id),
    CHECK (
        (event_kind = 'started' AND is_terminal = false)
        OR (event_kind <> 'started' AND is_terminal = true)
    )
);

-- At most one terminal event per attempt.
CREATE UNIQUE INDEX document_parser_attempt_one_terminal
ON atlas_ingestion.document_parser_attempt_events (tenant_id, workspace_id, attempt_id)
WHERE is_terminal;

-- Exactly-once started event per attempt.
CREATE UNIQUE INDEX document_parser_attempt_one_started
ON atlas_ingestion.document_parser_attempt_events (tenant_id, workspace_id, attempt_id)
WHERE event_kind = 'started';

CREATE TABLE atlas_ingestion.document_admission_assessments (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    assessment_id uuid NOT NULL,
    acquisition_id uuid NOT NULL,
    attempt_id uuid NOT NULL,
    artifact_id text NOT NULL,
    prior_admission_hash text NOT NULL CHECK (prior_admission_hash ~ '^[0-9a-f]{64}$'),
    lifecycle text NOT NULL,
    outcome text NOT NULL,
    reason_codes jsonb NOT NULL CHECK (
        jsonb_typeof(reason_codes) = 'array' AND jsonb_array_length(reason_codes) > 0
    ),
    assessment jsonb NOT NULL CHECK (jsonb_typeof(assessment) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, assessment_id),
    UNIQUE (tenant_id, workspace_id, attempt_id),
    FOREIGN KEY (tenant_id, workspace_id, acquisition_id)
        REFERENCES atlas_ingestion.document_acquisitions(tenant_id, workspace_id, acquisition_id),
    FOREIGN KEY (tenant_id, workspace_id, attempt_id)
        REFERENCES atlas_ingestion.document_parser_attempts(tenant_id, workspace_id, attempt_id)
);

CREATE TRIGGER document_parser_attempts_are_append_only
BEFORE UPDATE OR DELETE ON atlas_ingestion.document_parser_attempts
FOR EACH ROW EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER document_parser_attempts_reject_truncate
BEFORE TRUNCATE ON atlas_ingestion.document_parser_attempts
FOR EACH STATEMENT EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER document_parser_attempt_events_are_append_only
BEFORE UPDATE OR DELETE ON atlas_ingestion.document_parser_attempt_events
FOR EACH ROW EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER document_parser_attempt_events_reject_truncate
BEFORE TRUNCATE ON atlas_ingestion.document_parser_attempt_events
FOR EACH STATEMENT EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER document_admission_assessments_are_append_only
BEFORE UPDATE OR DELETE ON atlas_ingestion.document_admission_assessments
FOR EACH ROW EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();

CREATE TRIGGER document_admission_assessments_reject_truncate
BEFORE TRUNCATE ON atlas_ingestion.document_admission_assessments
FOR EACH STATEMENT EXECUTE FUNCTION atlas_ingestion.reject_evidence_mutation();
