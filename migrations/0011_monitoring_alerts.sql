-- Phase 5 monitoring: alerts, append-only lifecycle events, research invalidations.

CREATE SCHEMA IF NOT EXISTS atlas_monitoring;

CREATE TABLE atlas_monitoring.alerts (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    alert_id text NOT NULL CHECK (alert_id ~ '^alert:[0-9a-f]{64}$'),
    dedup_key text NOT NULL CHECK (dedup_key ~ '^[0-9a-f]{64}$'),
    rule_id text NOT NULL,
    subject_id text NOT NULL,
    severity text NOT NULL,
    status text NOT NULL,
    detected_at timestamptz NOT NULL,
    event_time timestamptz NOT NULL,
    current_observation_id text NOT NULL CHECK (current_observation_id ~ '^observation:[0-9a-f]{64}$'),
    current_envelope_id text NOT NULL CHECK (current_envelope_id ~ '^envelope:[0-9a-f]{64}$'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, alert_id),
    UNIQUE (tenant_id, workspace_id, dedup_key)
);

CREATE TABLE atlas_monitoring.alert_events (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    event_id text NOT NULL CHECK (event_id ~ '^alertevent:[0-9a-f]{64}$'),
    alert_id text NOT NULL CHECK (alert_id ~ '^alert:[0-9a-f]{64}$'),
    from_status text,
    to_status text NOT NULL,
    note text NOT NULL DEFAULT '',
    recorded_at timestamptz NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    PRIMARY KEY (tenant_id, workspace_id, event_id),
    FOREIGN KEY (tenant_id, workspace_id, alert_id)
        REFERENCES atlas_monitoring.alerts(tenant_id, workspace_id, alert_id)
);

CREATE TABLE atlas_monitoring.research_invalidations (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    invalidation_id text NOT NULL CHECK (invalidation_id ~ '^invalidation:[0-9a-f]{64}$'),
    reason text NOT NULL,
    subject_id text NOT NULL,
    observation_id text CHECK (observation_id IS NULL OR observation_id ~ '^observation:[0-9a-f]{64}$'),
    envelope_id text CHECK (envelope_id IS NULL OR envelope_id ~ '^envelope:[0-9a-f]{64}$'),
    alert_id text CHECK (alert_id IS NULL OR alert_id ~ '^alert:[0-9a-f]{64}$'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, invalidation_id)
);

CREATE INDEX alerts_subject_detected
ON atlas_monitoring.alerts (tenant_id, workspace_id, subject_id, detected_at DESC);

CREATE INDEX alert_events_alert_recorded
ON atlas_monitoring.alert_events (tenant_id, workspace_id, alert_id, recorded_at);

CREATE INDEX invalidations_subject_recorded
ON atlas_monitoring.research_invalidations (
    tenant_id, workspace_id, subject_id, recorded_at DESC
);
