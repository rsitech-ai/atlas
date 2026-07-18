import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from rsi_atlas_storage.database import PostgresDatabase

_MIGRATION_NAME = re.compile(r"^(?P<version>[0-9]{4})_[a-z0-9_]+\.sql$")
_MIGRATION_LOCK_ID = 0x52534941544C4153


class MigrationIntegrityError(RuntimeError):
    """Raised when migration history and the checked-in SQL no longer agree."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: str
    name: str
    checksum: str
    sql: str


class MigrationRunner:
    def __init__(self, database: PostgresDatabase, migration_directory: Path) -> None:
        self._database = database
        self._migration_directory = migration_directory

    def apply_all(self) -> None:
        migrations = self._load_migrations()
        with self._database.connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (_MIGRATION_LOCK_ID,))
            cursor.execute("CREATE SCHEMA IF NOT EXISTS atlas_meta")
            cursor.execute(
                """
                    CREATE TABLE IF NOT EXISTS atlas_meta.schema_migrations (
                        version text PRIMARY KEY,
                        name text NOT NULL,
                        checksum char(64) NOT NULL,
                        applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
                    )
                    """
            )
            for migration in migrations:
                cursor.execute(
                    "SELECT checksum FROM atlas_meta.schema_migrations WHERE version = %s",
                    (migration.version,),
                )
                applied = cursor.fetchone()
                if applied is not None:
                    if applied[0] != migration.checksum:
                        raise MigrationIntegrityError(
                            f"migration {migration.version} checksum does not match applied bytes"
                        )
                    continue
                cursor.execute(migration.sql)
                cursor.execute(
                    """
                        INSERT INTO atlas_meta.schema_migrations (version, name, checksum)
                        VALUES (%s, %s, %s)
                        """,
                    (migration.version, migration.name, migration.checksum),
                )

    def _load_migrations(self) -> tuple[Migration, ...]:
        if not self._migration_directory.is_dir():
            raise MigrationIntegrityError(
                f"migration directory is missing: {self._migration_directory}"
            )
        migrations: list[Migration] = []
        versions: set[str] = set()
        for path in sorted(self._migration_directory.glob("*.sql")):
            match = _MIGRATION_NAME.fullmatch(path.name)
            if match is None:
                raise MigrationIntegrityError(f"invalid migration filename: {path.name}")
            version = match.group("version")
            if version in versions:
                raise MigrationIntegrityError(f"duplicate migration version: {version}")
            versions.add(version)
            migration_bytes = path.read_bytes()
            try:
                sql = migration_bytes.decode("utf-8")
            except UnicodeDecodeError as error:
                raise MigrationIntegrityError(f"migration is not UTF-8: {path.name}") from error
            migrations.append(
                Migration(
                    version=version,
                    name=path.name,
                    checksum=hashlib.sha256(migration_bytes).hexdigest(),
                    sql=sql,
                )
            )
        return tuple(migrations)
