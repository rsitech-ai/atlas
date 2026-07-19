-- Phase 3 research runs, report drafts, and immutable review decisions.

CREATE SCHEMA IF NOT EXISTS atlas_research;

CREATE TABLE atlas_research.research_runs (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    run_id text NOT NULL CHECK (run_id ~ '^retrievalrun:[0-9a-f]{64}$'),
    query_id uuid NOT NULL,
    outcome text NOT NULL CHECK (outcome IN ('packet', 'abstain')),
    plan_hash text NOT NULL CHECK (plan_hash ~ '^[0-9a-f]{64}$'),
    cutoff_hash text NOT NULL CHECK (cutoff_hash ~ '^[0-9a-f]{64}$'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, run_id)
);

CREATE TABLE atlas_research.report_drafts (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    report_id text NOT NULL CHECK (report_id ~ '^report:[0-9a-f]{64}$'),
    run_id text NOT NULL CHECK (run_id ~ '^retrievalrun:[0-9a-f]{64}$'),
    version integer NOT NULL CHECK (version >= 1),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, report_id),
    UNIQUE (tenant_id, workspace_id, run_id, version),
    FOREIGN KEY (tenant_id, workspace_id, run_id)
        REFERENCES atlas_research.research_runs(tenant_id, workspace_id, run_id)
);

CREATE TABLE atlas_research.review_decisions (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    decision_id uuid NOT NULL,
    report_id text NOT NULL CHECK (report_id ~ '^report:[0-9a-f]{64}$'),
    action text NOT NULL,
    rationale text NOT NULL CHECK (length(rationale) > 0),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, decision_id),
    FOREIGN KEY (tenant_id, workspace_id, report_id)
        REFERENCES atlas_research.report_drafts(tenant_id, workspace_id, report_id)
);

CREATE INDEX research_runs_recorded
ON atlas_research.research_runs (tenant_id, workspace_id, recorded_at);

CREATE INDEX review_decisions_report
ON atlas_research.review_decisions (tenant_id, workspace_id, report_id, recorded_at);
