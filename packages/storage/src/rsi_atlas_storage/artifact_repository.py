from typing import cast

from rsi_atlas_contracts import (
    ArtifactCommandContext,
    ArtifactDescriptor,
    ArtifactID,
    ArtifactIntegrityError,
)

from rsi_atlas_storage.artifact_store import ContentAddressedArtifactStore
from rsi_atlas_storage.database import PostgresDatabase


class ArtifactRepository:
    def __init__(
        self, database: PostgresDatabase, artifact_store: ContentAddressedArtifactStore
    ) -> None:
        self._database = database
        self._artifact_store = artifact_store

    def register(
        self, *, context: ArtifactCommandContext, descriptor: ArtifactDescriptor
    ) -> ArtifactDescriptor:
        command_context = self._require_context(context)
        verified = self._artifact_store.verify(descriptor.artifact_id, context=command_context)
        if verified != descriptor:
            raise ArtifactIntegrityError("registered descriptor differs from verified artifact")

        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO atlas_core.tenants (id) VALUES (%s) ON CONFLICT DO NOTHING",
                (command_context.tenant_id,),
            )
            cursor.execute(
                "SELECT tenant_id FROM atlas_core.workspaces WHERE id = %s",
                (command_context.workspace_id,),
            )
            workspace = cursor.fetchone()
            if workspace is not None and workspace[0] != command_context.tenant_id:
                raise PermissionError("workspace belongs to another tenant")
            cursor.execute(
                """
                    INSERT INTO atlas_core.workspaces (id, tenant_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                (command_context.workspace_id, command_context.tenant_id),
            )
            cursor.execute(
                "SELECT tenant_id FROM atlas_core.actors WHERE id = %s",
                (command_context.actor_id,),
            )
            actor = cursor.fetchone()
            if actor is not None and actor[0] != command_context.tenant_id:
                raise PermissionError("actor belongs to another tenant")
            cursor.execute(
                """
                    INSERT INTO atlas_core.actors (id, tenant_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                (command_context.actor_id, command_context.tenant_id),
            )
            cursor.execute(
                """
                    INSERT INTO atlas_core.artifact_contents (
                        artifact_id, digest, schema_version, algorithm, size_bytes, media_type
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                (
                    str(descriptor.artifact_id),
                    descriptor.digest,
                    descriptor.schema_version,
                    descriptor.algorithm,
                    descriptor.size_bytes,
                    descriptor.media_type,
                ),
            )
            cursor.execute(
                """
                SELECT digest, schema_version, algorithm, size_bytes, media_type
                FROM atlas_core.artifact_contents
                WHERE artifact_id = %s
                """,
                (str(descriptor.artifact_id),),
            )
            stored_content = cursor.fetchone()
            expected_content = (
                descriptor.digest,
                descriptor.schema_version,
                descriptor.algorithm,
                descriptor.size_bytes,
                descriptor.media_type,
            )
            if stored_content != expected_content:
                raise ArtifactIntegrityError(
                    "stored artifact metadata differs from verified descriptor"
                )
            cursor.execute(
                """
                    INSERT INTO atlas_core.artifact_references (
                        tenant_id,
                        workspace_id,
                        artifact_id,
                        registered_by_actor_id,
                        registration_trace_id
                    ) VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                (
                    command_context.tenant_id,
                    command_context.workspace_id,
                    str(descriptor.artifact_id),
                    command_context.actor_id,
                    command_context.trace_id,
                ),
            )
        return descriptor

    def find(
        self, *, context: ArtifactCommandContext, artifact_id: ArtifactID
    ) -> ArtifactDescriptor | None:
        command_context = self._require_context(context)
        row = self._database.fetch_one(
            """
            SELECT
                c.artifact_id,
                c.digest,
                c.schema_version,
                c.algorithm,
                c.size_bytes,
                c.media_type
            FROM atlas_core.artifact_references AS r
            JOIN atlas_core.artifact_contents AS c USING (artifact_id)
            WHERE r.tenant_id = %s AND r.workspace_id = %s AND r.artifact_id = %s
            """,
            (
                command_context.tenant_id,
                command_context.workspace_id,
                str(artifact_id),
            ),
        )
        if row is None:
            return None
        descriptor = ArtifactDescriptor(
            artifact_id=cast(ArtifactID, row[0]),
            digest=row[1],
            schema_version=row[2],
            algorithm=row[3],
            size_bytes=row[4],
            media_type=row[5],
        )
        verified = self._artifact_store.verify(artifact_id, context=command_context)
        if verified != descriptor:
            raise ArtifactIntegrityError(
                "stored artifact metadata differs from verified descriptor"
            )
        return descriptor

    @staticmethod
    def _require_context(context: ArtifactCommandContext) -> ArtifactCommandContext:
        return ArtifactCommandContext.model_validate(context)
