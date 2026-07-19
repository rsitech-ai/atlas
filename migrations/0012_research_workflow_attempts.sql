-- Durable linear research workflow checkpoints (interrupt/resume).

CREATE TABLE atlas_research.research_workflow_attempts (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    workflow_id uuid NOT NULL,
    query_id uuid NOT NULL,
    step text NOT NULL CHECK (
        step IN (
            'planned',
            'retrieved',
            'specialist_done',
            'drafted',
            'awaiting_human',
            'completed',
            'aborted'
        )
    ),
    run_id text,
    packet_id text,
    finding_task_id text,
    report_id text,
    detail text NOT NULL DEFAULT '' CHECK (length(detail) <= 512),
    title text NOT NULL DEFAULT '' CHECK (length(title) <= 256),
    checkpoint jsonb NOT NULL CHECK (jsonb_typeof(checkpoint) = 'object'),
    query_payload jsonb CHECK (query_payload IS NULL OR jsonb_typeof(query_payload) = 'object'),
    packet_payload jsonb CHECK (packet_payload IS NULL OR jsonb_typeof(packet_payload) = 'object'),
    finding_payload jsonb CHECK (
        finding_payload IS NULL OR jsonb_typeof(finding_payload) = 'object'
    ),
    report_payload jsonb CHECK (report_payload IS NULL OR jsonb_typeof(report_payload) = 'object'),
    updated_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, workflow_id)
);

CREATE INDEX research_workflow_attempts_updated
ON atlas_research.research_workflow_attempts (tenant_id, workspace_id, updated_at DESC);

CREATE INDEX research_workflow_attempts_query
ON atlas_research.research_workflow_attempts (tenant_id, workspace_id, query_id);
