"""FastAPI backend for user-manual skill (db mode).

Endpoints:
  GET  /health                          liveness
  GET  /api/config                      viewer config (api base, object_store url, auth)
  GET  /api/manuals                     list (returns manual-index.json shape)
  GET  /api/manuals/{file}              single manual body + assets list
  GET  /api/manuals/{file}/assets/{object_key:path}  redirect to object store public URL
  POST /api/manuals                     upsert a manual (used by skill helper; no auth in MVP)
  POST /api/manuals/{file}/assets      upload asset, returns {object_key, public_url}

DB: Postgres via asyncpg + sqlalchemy async.
Object store: S3-compatible (MinIO default). public_base_url is for viewer to load assets.
"""
import os
import re
import asyncio
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List
from contextlib import asynccontextmanager

import asyncpg
import boto3
from botocore.client import Config as BotoConfig
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

# ---- config from env (overridable) ----
DB_DSN = os.environ.get("MANUAL_DB_DSN", "postgresql://user:CHANGE_ME@localhost:5432/user_manual")
S3_ENDPOINT = os.environ.get("MANUAL_S3_ENDPOINT", "http://localhost:9100")
S3_ACCESS_KEY = os.environ.get("MANUAL_S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.environ.get("MANUAL_S3_SECRET_KEY", "minioadmin")
S3_BUCKET = os.environ.get("MANUAL_S3_BUCKET", "manuals")
S3_PUBLIC_BASE = os.environ.get("MANUAL_S3_PUBLIC_BASE", f"{S3_ENDPOINT}/{S3_BUCKET}")
S3_REGION = os.environ.get("MANUAL_S3_REGION", "us-east-1")
API_PUBLIC_BASE = os.environ.get("MANUAL_API_PUBLIC_BASE", "http://localhost:8000")
AUTH_ENABLED = os.environ.get("MANUAL_AUTH_ENABLED", "false").lower() == "true"
AUTH_TOKEN = os.environ.get("MANUAL_AUTH_TOKEN", "")

# ---- shared resources ----
_db_pool: Optional[asyncpg.Pool] = None
_s3 = None
_s3_public = None  # for get-object (presigned url generation if needed)

def _s3_client():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION,
        config=BotoConfig(signature_version="s3v4"),
    )

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _db_pool, _s3
    _db_pool = await asyncpg.create_pool(DB_DSN, min_size=1, max_size=5)
    _s3 = _s3_client()
    # Ensure bucket exists
    try:
        _s3.head_bucket(Bucket=S3_BUCKET)
    except Exception:
        _s3.create_bucket(Bucket=S3_BUCKET)
    print(f"[user-manual-api] started — db={DB_DSN.split('@')[-1]} s3={S3_ENDPOINT}/{S3_BUCKET}")
    yield
    await _db_pool.close()

app = FastAPI(title="user-manual-api", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- auth (optional) ----
def check_auth(headers):
    if not AUTH_ENABLED:
        return
    if headers.get("authorization", "").replace("Bearer ", "") != AUTH_TOKEN:
        raise HTTPException(401, "invalid token")

# ---- response models ----
class ModuleOut(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    order_index: int = 0

class ManualSummary(BaseModel):
    file: str
    title: str
    module: str
    module_code: Optional[str] = None
    description: Optional[str] = None
    order: int
    version: str
    version_date: Optional[str] = None

class AssetOut(BaseModel):
    object_key: str
    original_name: str
    kind: str
    mime_type: Optional[str] = None
    caption: Optional[str] = None
    public_url: str

class ManualDetail(ManualSummary):
    body_md: str
    raw_md: Optional[str] = None
    assets: List[AssetOut] = []

class ManualUpsert(BaseModel):
    file: str
    module: str                                              # 显示名(中文友好)
    module_code: Optional[str] = None                        # 机器可读 key(英文/数字/下划线,作 S3 prefix)
    title: str
    description: Optional[str] = None
    order: int = 999
    version: str = "v0.1"
    version_date: Optional[str] = None  # "YYYY-MM-DD"
    body_md: str
    raw_md: Optional[str] = None

# ---- routes ----
@app.get("/health")
async def health():
    return {"ok": True, "ts": datetime.utcnow().isoformat()}

@app.get("/api/config")
async def get_config():
    """Returns viewer-relevant runtime config.

    Note: storage: "db" is hard-coded here; the file-mode viewer is used
    when the page is opened directly via file:// and never reaches this endpoint.
    """
    return {
        "storage": "db",
        "api": {"base_url": API_PUBLIC_BASE},
        "object_store": {"public_base_url": S3_PUBLIC_BASE},
        "auth": {"enabled": AUTH_ENABLED},
    }

@app.get("/api/manuals", response_model=List[ManualSummary])
async def list_manuals():
    """Returns the manual-index.json shape (what the viewer uses on load)."""
    async with _db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT m.file, m.title, COALESCE(mod.code, '') AS module_code,
                   COALESCE(mod.name, '') AS module_name, m.description,
                   m.order_index, m.version, m.version_date
            FROM manuals m
            LEFT JOIN modules mod ON mod.id = m.module_id
            ORDER BY COALESCE(mod.order_index, 0), m.order_index, m.title
        """)
    out = []
    for r in rows:
        out.append({
            "file": r["file"],
            "title": r["title"],
            "module": r["module_name"],
            "module_code": r["module_code"] or None,
            "description": r["description"],
            "order": r["order_index"],
            "version": r["version"],
            "version_date": r["version_date"].isoformat() if r["version_date"] else None,
        })
    return out

@app.get("/api/manuals/{file:path}", response_model=ManualDetail)
async def get_manual(file: str):
    async with _db_pool.acquire() as conn:
        mrow = await conn.fetchrow("""
            SELECT m.id, m.file, m.title, m.description, m.body_md, m.raw_md,
                   m.order_index, m.version, m.version_date,
                   COALESCE(mod.code, '') AS module_code,
                   COALESCE(mod.name, '') AS module_name
            FROM manuals m LEFT JOIN modules mod ON mod.id = m.module_id
            WHERE m.file = $1
        """, file)
        if not mrow:
            raise HTTPException(404, f"manual not found: {file}")
        arows = await conn.fetch("""
            SELECT object_key, original_name, kind, mime_type, caption
            FROM manual_assets WHERE manual_id = $1 ORDER BY id
        """, mrow["id"])
    assets = [
        {
            "object_key": a["object_key"],
            "original_name": a["original_name"],
            "kind": a["kind"],
            "mime_type": a["mime_type"],
            "caption": a["caption"],
            "public_url": f"{S3_PUBLIC_BASE}/{a['object_key']}",
        }
        for a in arows
    ]
    return {
        "file": mrow["file"],
        "title": mrow["title"],
        "module": mrow["module_name"],
        "module_code": mrow["module_code"] or None,
        "description": mrow["description"],
        "order": mrow["order_index"],
        "version": mrow["version"],
        "version_date": mrow["version_date"].isoformat() if mrow["version_date"] else None,
        "body_md": mrow["body_md"],
        "raw_md": mrow["raw_md"],
        "assets": assets,
    }

@app.post("/api/manuals", response_model=ManualSummary)
async def upsert_manual(m: ManualUpsert):
    """Upsert a manual row. Module is auto-created by code if missing."""
    vd = None
    if m.version_date:
        try:
            vd = date.fromisoformat(m.version_date)
        except ValueError:
            raise HTTPException(400, f"version_date must be YYYY-MM-DD, got {m.version_date!r}")
    async with _db_pool.acquire() as conn:
        async with conn.transaction():
            # module_code 解析优先级(便于跨项目复用):
            #   1. m.module_code 显式传入(推荐:md frontmatter `module_code: FR`)
            #   2. 从 m.module 字符串推一个 ASCII slug(中文 → transliterated 或 fallback)
            #   3. 占位 "MISC"
            import re as _re
            raw_code = (m.module_code or "").strip()
            if not raw_code:
                # 尝试 ASCII 化:保留 a-zA-Z0-9_-,其余替换为 _,然后 collapse
                raw_code = _re.sub(r"[^A-Za-z0-9_-]+", "_", m.module or "").strip("_")
            module_code = raw_code or "MISC"
            await conn.execute("""
                INSERT INTO modules (code, name) VALUES ($1, $2)
                ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name
            """, module_code, m.module or module_code)
            mod = await conn.fetchrow("SELECT id FROM modules WHERE code = $1", module_code)
            await conn.execute("""
                INSERT INTO manuals
                  (file, module_id, title, description, order_index, version, version_date, body_md, raw_md, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, now())
                ON CONFLICT (file) DO UPDATE SET
                  module_id = EXCLUDED.module_id,
                  title = EXCLUDED.title,
                  description = EXCLUDED.description,
                  order_index = EXCLUDED.order_index,
                  version = EXCLUDED.version,
                  version_date = EXCLUDED.version_date,
                  body_md = EXCLUDED.body_md,
                  raw_md = EXCLUDED.raw_md,
                  updated_at = now()
            """, m.file, mod["id"], m.title, m.description, m.order, m.version, vd, m.body_md, m.raw_md)
    return {
        "file": m.file,
        "title": m.title,
        "module": m.module,
        "module_code": module_code,
        "description": m.description,
        "order": m.order,
        "version": m.version,
        "version_date": m.version_date,
    }

@app.post("/api/manuals/{file:path}/assets")
async def upload_asset(
    file: str,
    upload: UploadFile = File(...),
    caption: str = Form(""),
):
    """Upload a binary asset. Stores to S3 under {module_code}/{filename},
    inserts a row in manual_assets with the public URL.

    NOTE: simpler than letting caller pick object_key — we derive it from
    module code + original filename. If filename collides, append timestamp.
    """
    async with _db_pool.acquire() as conn:
        mrow = await conn.fetchrow("""
            SELECT m.id, COALESCE(mod.code, 'misc') AS module_code
            FROM manuals m LEFT JOIN modules mod ON mod.id = m.module_id
            WHERE m.file = $1
        """, file)
        if not mrow:
            raise HTTPException(404, f"manual not found: {file}")
        manual_id = mrow["id"]
        # 直接用 module code 字符串(允许中文, MinIO/S3 SDK 都支持 unicode key)
        mod_code = mrow["module_code"] or "misc"

    # derive object key
    safe_name = re.sub(r"[^\w.\-]+", "_", upload.filename or "asset")
    object_key = f"{mod_code}/{safe_name}"
    # check collision
    s3 = _s3
    try:
        s3.head_object(Bucket=S3_BUCKET, Key=object_key)
        stem = Path(safe_name).stem
        suf = Path(safe_name).suffix
        object_key = f"{mod_code}/{stem}-{int(datetime.utcnow().timestamp())}{suf}"
    except Exception:
        pass

    body = await upload.read()
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=object_key,
        Body=body,
        ContentType=upload.content_type or "application/octet-stream",
    )
    kind = "image" if (upload.content_type or "").startswith("image/") else \
           "video" if (upload.content_type or "").startswith("video/") else "other"
    async with _db_pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO manual_assets
              (manual_id, object_key, original_name, kind, mime_type, size_bytes, caption)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (object_key) DO UPDATE SET
              original_name = EXCLUDED.original_name,
              mime_type = EXCLUDED.mime_type,
              size_bytes = EXCLUDED.size_bytes,
              caption = EXCLUDED.caption
        """, manual_id, object_key, upload.filename or "asset", kind,
             upload.content_type, len(body), caption)
    return {
        "object_key": object_key,
        "public_url": f"{S3_PUBLIC_BASE}/{object_key}",
        "kind": kind,
        "mime_type": upload.content_type,
        "size": len(body),
    }
