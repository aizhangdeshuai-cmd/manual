# db-backend (reference implementation)

FastAPI + Postgres + S3-compatible object store backend for the
`user-manual` skill's **db storage mode**.

This is a working reference implementation, not a published package. Copy
the two files (`app.py` + `schema.sql`) into your project, point env vars
at your infra, and run. Total: ~370 lines.

## Why a reference and not a hard dependency

The skill's default mode is `file` (markdown on disk + a self-contained
HTML viewer). `db` mode is for teams that want:

- Multiple readers at a single canonical URL
- Edit-publish workflow without redeploying static files
- Asset uploads through a backend rather than commit-to-git
- Auth in front of the manual (e.g. behind SSO)

If you don't need any of that, **skip this folder entirely** and use the
`file` mode — it works without Postgres, without S3, without an API
process.

## Layout

```
examples/db-backend/
├── app.py            FastAPI app, 323 lines, 6 endpoints
├── schema.sql        3 tables (modules / manuals / manual_assets)
└── README.md         this file
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | liveness |
| GET | `/api/config` | viewer config (`storage: "db"`, `api.base_url`, `object_store.public_base_url`, `auth`) |
| GET | `/api/manuals` | list, returns `manual-index.json` shape |
| GET | `/api/manuals/{file}` | one manual: frontmatter + body_md + assets[] |
| POST | `/api/manuals` | upsert (used by `manual_helper.py upsert-manual`) |
| POST | `/api/manuals/{file}/assets` | upload binary to S3, returns `{object_key, public_url}` |

## Storage schema

```text
modules             (code PK, name, description, order_index)
  └── manuals       (file PK, module_id FK, title, body_md, raw_md,
                     version, version_date, order_index, timestamps)
       └── manual_assets  (object_key PK, manual_id FK, original_name,
                           kind, mime_type, size_bytes, caption)
```

`object_key` for an asset follows `{module_code}/{safe_filename}`.
`module_code` is the ASCII-safe key (see below); unicode modules are
allowed but generate ugly URLs.

## Module name vs module code

The viewer shows the **module name** (display, can be Chinese). The API
uses the **module code** (machine key, ASCII) as the S3 prefix.

Resolution order on upsert:

1. `manual_helper.py` reads the md file's YAML frontmatter. If
   `module_code:` is set, it sends both `module` and `module_code` to
   the API.
2. If only `module:` is set, the API derives `module_code` by
   ASCII-slugifying the module name (`[^A-Za-z0-9_-]+` → `_`).
3. If neither is set, falls back to `"MISC"`.

Example frontmatter:

```yaml
---
title: My Project — Admin Manual
module: System Overview           # display name (any language OK)
module_code: SYS                  # optional; ASCII slug used as S3 prefix
description: ...
order: 1
---
```

## Running

```bash
# 1. Apply schema (idempotent — drops & recreates; use cautiously in prod)
psql "$MANUAL_DB_DSN" -f schema.sql

# 2. Run the API
pip install fastapi 'uvicorn[standard]' asyncpg boto3 'pydantic>=2'
export MANUAL_DB_DSN="postgresql://user:pass@host:5432/user_manual"
export MANUAL_S3_ENDPOINT="http://localhost:9100"
export MANUAL_S3_BUCKET="manuals"
export MANUAL_S3_PUBLIC_BASE="http://localhost:9100/manuals"  # viewer uses this to load images
export MANUAL_API_PUBLIC_BASE="http://localhost:8000"          # advertised to viewer in /api/config
uvicorn app:app --host 0.0.0.0 --port 8000
```

The API auto-creates the bucket on first start if it doesn't exist.

## Environment variables

| Var | Default | Purpose |
|---|---|---|
| `MANUAL_DB_DSN` | `postgresql://user:CHANGE_ME@localhost:5432/user_manual` | Postgres DSN |
| `MANUAL_S3_ENDPOINT` | (none — required) | S3/MinIO endpoint URL |
| `MANUAL_S3_BUCKET` | `manuals` | bucket name |
| `MANUAL_S3_ACCESS_KEY` | (none) | S3 access key |
| `MANUAL_S3_SECRET_KEY` | (none) | S3 secret key |
| `MANUAL_S3_REGION` | `us-east-1` | S3 region |
| `MANUAL_S3_PUBLIC_BASE` | `${S3_ENDPOINT}/${S3_BUCKET}` | base URL the viewer prepends to `object_key` |
| `MANUAL_API_PUBLIC_BASE` | `http://localhost:8000` | advertised to viewer; used to build absolute URLs in responses |
| `MANUAL_AUTH_ENABLED` | `false` | enable bearer token auth |
| `MANUAL_AUTH_TOKEN` | (empty) | the expected bearer token |

Defaults with `CHANGE_ME` are deliberately broken so you must set
`MANUAL_DB_DSN` explicitly before first run. Everything else has a
sensible default for local dev.

## Auth

MVP. `MANUAL_AUTH_ENABLED=true` plus `MANUAL_AUTH_TOKEN=<something>`
turns on a single static bearer token. The viewer reads
`auth.token` from `manual-config.json` and sends it as
`Authorization: Bearer <token>`. Replace `check_auth()` in `app.py` with
real auth (JWT verify, OAuth introspection, etc.) for production.

## Production hardening (not done here)

- `schema.sql` drops tables on every init. For prod, switch to
  forward-only migrations (Flyway / Alembic / sqlx-cli).
- `check_auth()` is a single static token. Replace.
- CORS is `allow_origins=["*"]`. Lock down to your viewer origin.
- No rate limiting. Add `slowapi` or front it with a gateway.
- `boto3` uploads are unauthenticated reads. If your bucket is private,
  set `public_base_url` to a presigned-URL endpoint or front S3 with
  CloudFront.
