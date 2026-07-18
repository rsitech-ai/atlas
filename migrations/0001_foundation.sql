CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS atlas_core;

CREATE TABLE IF NOT EXISTS atlas_core.tenants (
    id uuid PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS atlas_core.workspaces (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES atlas_core.tenants(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS atlas_core.actors (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES atlas_core.tenants(id),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id, id)
);

CREATE TABLE IF NOT EXISTS atlas_core.artifact_contents (
    artifact_id text PRIMARY KEY CHECK (artifact_id ~ '^sha256:[0-9a-f]{64}$'),
    digest char(64) NOT NULL UNIQUE CHECK (digest ~ '^[0-9a-f]{64}$'),
    schema_version text NOT NULL,
    algorithm text NOT NULL CHECK (algorithm = 'sha256'),
    size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
    media_type text NOT NULL CHECK (length(media_type) > 0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (artifact_id = 'sha256:' || digest)
);

CREATE TABLE IF NOT EXISTS atlas_core.artifact_references (
    tenant_id uuid NOT NULL,
    workspace_id uuid NOT NULL,
    artifact_id text NOT NULL REFERENCES atlas_core.artifact_contents(artifact_id),
    registered_by_actor_id uuid NOT NULL,
    registration_trace_id uuid NOT NULL,
    registered_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, workspace_id, artifact_id),
    FOREIGN KEY (tenant_id, workspace_id)
        REFERENCES atlas_core.workspaces(tenant_id, id),
    FOREIGN KEY (tenant_id, registered_by_actor_id)
        REFERENCES atlas_core.actors(tenant_id, id)
);
