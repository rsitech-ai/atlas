# DuckDB / Parquet analytics dependency approval

Status: **approved** (optional local analytics; PostgreSQL remains system of record)

## Decision

Approved on 2026-07-19 by actor `andrzej:oss-production-ready-instruction`.

DuckDB is MIT-licensed. Optional package `duckdb` may be used for **local** Parquet export /
ad-hoc analytics under the owner-private data root. No remote DuckDB / MotherDuck.

### Allowed

- Optional dependency `duckdb` (MIT) when `RSI_ATLAS_ENABLE_DUCKDB=1` and the package imports
- Local file DB + `COPY`/`read_parquet` under owner-private paths only
- Gate status `available` only when import succeeds; otherwise remain `blocked_dependency`

### Not allowed

- Networked DuckDB / cloud analytics
- Replacing PostgreSQL as operational SoT
- Silent auto-install of duckdb wheels at runtime

### Rollback

Unset `RSI_ATLAS_ENABLE_DUCKDB`; remove optional extra; keep Postgres-only gates.
