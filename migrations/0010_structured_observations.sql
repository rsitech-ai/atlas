-- Phase 4 structured observations: raw envelopes, normalized observations, quarantine.

CREATE SCHEMA IF NOT EXISTS atlas_observations;

CREATE TABLE atlas_observations.raw_envelopes (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    envelope_id text NOT NULL CHECK (envelope_id ~ '^envelope:[0-9a-f]{64}$'),
    collector_id text NOT NULL,
    provider text NOT NULL,
    source_family text NOT NULL,
    payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    payload_artifact_id text NOT NULL CHECK (payload_artifact_id ~ '^sha256:[0-9a-f]{64}$'),
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, envelope_id)
);

CREATE TABLE atlas_observations.observations (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    observation_id text NOT NULL CHECK (observation_id ~ '^observation:[0-9a-f]{64}$'),
    envelope_id text NOT NULL CHECK (envelope_id ~ '^envelope:[0-9a-f]{64}$'),
    source_family text NOT NULL,
    observation_type text NOT NULL,
    subject_ids text[] NOT NULL CHECK (cardinality(subject_ids) >= 1),
    event_time timestamptz NOT NULL,
    available_time timestamptz NOT NULL,
    valid_time timestamptz NOT NULL,
    system_time timestamptz NOT NULL,
    quality text NOT NULL,
    provider_quality text NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, observation_id),
    FOREIGN KEY (tenant_id, workspace_id, envelope_id)
        REFERENCES atlas_observations.raw_envelopes(tenant_id, workspace_id, envelope_id)
);

CREATE TABLE atlas_observations.quarantine (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    quarantine_id uuid NOT NULL,
    envelope_id text NOT NULL CHECK (envelope_id ~ '^envelope:[0-9a-f]{64}$'),
    observation_id text CHECK (observation_id IS NULL OR observation_id ~ '^observation:[0-9a-f]{64}$'),
    reasons text[] NOT NULL CHECK (cardinality(reasons) >= 1),
    severity text NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    recorded_at timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, workspace_id, quarantine_id),
    FOREIGN KEY (tenant_id, workspace_id, envelope_id)
        REFERENCES atlas_observations.raw_envelopes(tenant_id, workspace_id, envelope_id)
);

CREATE INDEX observations_as_of
ON atlas_observations.observations (
    tenant_id, workspace_id, available_time, valid_time
);

CREATE INDEX observations_subjects
ON atlas_observations.observations
USING gin (subject_ids);

CREATE INDEX quarantine_envelope
ON atlas_observations.quarantine (tenant_id, workspace_id, envelope_id, recorded_at);
