
from __future__ import annotations
import asyncio
import json
import mimetypes
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_FILENAME = "manual-config.json"
# 配置文件查找路径(按这个顺序)
CONFIG_SEARCH_PATHS = [
    "docs/user-manual/manual-config.json",   # 项目级(<project>/docs/user-manual/ 风格)
    "manual-config.json",                    # 仓库根
]

def find_config(start_dir: Path) -> Path | None:
    """从 start_dir 向上找 manual-config.json(优先近的)。
    额外查找 docs/user-manual/manual-config.json(项目级,GCR 风格)。"""
    cur = start_dir.resolve()
    for parent in [cur, *cur.parents]:
        cand = parent / CONFIG_FILENAME
        if cand.exists():
            return cand
    # 备选: 项目根的 docs/user-manual/ 下面
    for parent in [cur, *cur.parents]:
        cand = parent / "docs" / "user-manual" / CONFIG_FILENAME
        if cand.exists():
            return cand
    return None

def load_config() -> dict:
    """从 cwd 向上找 manual-config.json, 没找到给一个 file 模式默认 config。"""
    cfg_path = find_config(Path.cwd())
    if not cfg_path:
        return {
            "storage": "file",
            "object_store": "minio",
            "object_store_config": {
                "endpoint": "http://localhost:9100",
                "bucket": "manuals",
                "access_key": "minioadmin",
                "secret_key": "minioadmin",
                "public_base_url": "http://localhost:9100/manuals",
            },
            "db": {"dsn": "postgresql://user:CHANGE_ME@localhost:5432/user_manual"},
            "api": {"base_url": "http://localhost:8765"},
            "auth": {"enabled": False, "token": ""},
        }
    with cfg_path.open(encoding="utf-8") as f:
        return json.load(f)

def api_base_from_config(cfg: dict) -> str:
    return cfg.get("api", {}).get("base_url", "http://localhost:8765").rstrip("/")

def read_md_split(raw_md: str) -> tuple[dict, str]:
    """(frontmatter, body) — 与 _parse_frontmatter 行为一致。"""
    fm, body = _parse_frontmatter(raw_md)
    return fm, body

def http_post_json(url: str, payload: dict, token: str = "") -> dict:
    """POST JSON. 简单实现, 不引外部依赖。"""
    import urllib.request, urllib.error
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST {url} -> {e.code} {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"POST {url} unreachable: {e.reason}") from e

def http_post_multipart(url: str, file_path: Path, caption: str, token: str = "") -> dict:
    """POST multipart/form-data, 单个 file 字段 + caption。"""
    import urllib.request, urllib.error, uuid, mimetypes
    boundary = f"----manual{uuid.uuid4().hex}"
    headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    parts: list[bytes] = []
    def add_field(name: str, value: str):
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(value.encode("utf-8"))
        parts.append(b"\r\n")
    def add_file(name: str, filename: str, content: bytes, mime: str):
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        )
        parts.append(f"Content-Type: {mime}\r\n\r\n".encode())
        parts.append(content)
        parts.append(b"\r\n")
    add_field("caption", caption)
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    add_file("upload", file_path.name, file_path.read_bytes(), mime)
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"POST {url} -> {e.code} {e.read().decode('utf-8', 'replace')}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"POST {url} unreachable: {e.reason}") from e

# ---- new subcommands ----

def cmd_read_config(_args):
    cfg = load_config()
    cfg_path = find_config(Path.cwd())
    print(f"# source: {cfg_path or '(defaults, no config file found)'}")
    print(json.dumps(cfg, indent=2, ensure_ascii=False))

def cmd_init_db(args):
    """init-db: 把 schema 推到 DB(创建表, drop existing)。
    schema.sql 路径: <skill_dir>/db/schema.sql, 或 环境变量 MANUAL_DB_SCHEMA。
    """
    import urllib.request
    cfg = load_config()
    if cfg.get("storage") != "db":
        print(f"WARN: storage={cfg.get('storage')!r}, 仍按 db 模式执行", file=sys.stderr)
    dsn = cfg.get("db", {}).get("dsn") or os.environ.get("MANUAL_DB_DSN", "")
    if not dsn:
        print("error: no db.dsn in config and MANUAL_DB_DSN not set", file=sys.stderr)
        return 1
    # 找 schema.sql
    skill_dir = Path(__file__).resolve().parent.parent  # skill-template/scripts/.. -> skill-template
    schema_candidates = [
        skill_dir / "db" / "schema.sql",
        skill_dir.parent / "user-manual-api" / "schema.sql",  # 项目级 db 旁
        Path.cwd() / "docs" / "user-manual-api" / "schema.sql",
    ]
    schema_path = next((p for p in schema_candidates if p.exists()), None)
    if not schema_path:
        print(f"error: schema.sql not found, tried: {[str(p) for p in schema_candidates]}", file=sys.stderr)
        return 1
    sql = schema_path.read_text(encoding="utf-8")
    # 用 psycopg2 风格? 不引外部依赖, 用 asyncpg 在 subprocess 里跑
    # 简化: 用 docker exec / 直接 psql 都不行(helper 是纯 stdlib)
    # 走 API? schema 推送不走 API(API 不应能 drop)。这里直接 require asyncpg。
    try:
        import asyncpg
    except ImportError:
        print("error: asyncpg required for init-db. install: pip install asyncpg", file=sys.stderr)
        return 1
    async def run():
        conn = await asyncpg.connect(dsn)
        try:
            await conn.execute(sql)
        finally:
            await conn.close()
    asyncio.run(run())
    print(f"initialized: {dsn} (schema: {schema_path})")
    return 0

def cmd_upsert_manual(args):
    """upsert-manual <md-path>: 读 md, 拆 frontmatter/body, POST /api/manuals."""
    if len(args) != 1:
        print("usage: manual_helper.py upsert-manual <md-path>", file=sys.stderr)
        return 2
    md_path = Path(args[0])
    if not md_path.exists():
        print(f"error: {md_path} not found", file=sys.stderr)
        return 1
    cfg = load_config()
    if cfg.get("storage") != "db":
        print(f"error: storage={cfg.get('storage')!r}, db mode only", file=sys.stderr)
        return 1
    raw = md_path.read_text(encoding="utf-8")
    fm, body = read_md_split(raw)
    # module / module_code 双字段:
    # - module:  显示名(可中文,可含空格)
    # - module_code: 机器可读 key(英文/数字/下划线,作 S3 prefix)
    # 没显式给 module_code 时,API 端会用 module 字段兜底(ASCII-slugify,中文 → MISC)
    payload = {
        "file": md_path.name,
        "module": fm.get("module") or fm.get("module_code") or "MISC",
        "module_code": fm.get("module_code") or None,
        "title": fm.get("title") or md_path.stem,
        "description": fm.get("description") or None,
        "order": int(fm["order"]) if str(fm.get("order", "")).isdigit() else 999,
        "version": fm.get("version") or "v0.1",
        "version_date": fm.get("version_date") or None,
        "body_md": body,
        "raw_md": raw,
    }
    url = f"{api_base_from_config(cfg)}/api/manuals"
    token = cfg.get("auth", {}).get("token", "") if cfg.get("auth", {}).get("enabled") else ""
    try:
        r = http_post_json(url, payload, token)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"upserted: {r.get('file')} (id={r.get('id', '?')}, version={r.get('version')})")
    return 0

def cmd_upload_asset(args):
    """upload-asset <manual-file> <asset-path> [--caption TEXT]"""
    if len(args) < 2:
        print("usage: manual_helper.py upload-asset <manual-file-name> <asset-path> [--caption TEXT]", file=sys.stderr)
        return 2
    manual_file = args[0]
    asset_path = Path(args[1])
    caption = ""
    if "--caption" in args:
        i = args.index("--caption")
        if i + 1 < len(args):
            caption = args[i + 1]
    if not asset_path.exists():
        print(f"error: {asset_path} not found", file=sys.stderr)
        return 1
    cfg = load_config()
    if cfg.get("storage") != "db":
        print(f"error: storage={cfg.get('storage')!r}, db mode only", file=sys.stderr)
        return 1
    # 1) ensure manual exists
    fm_url = f"{api_base_from_config(cfg)}/api/manuals"
    token = cfg.get("auth", {}).get("token", "") if cfg.get("auth", {}).get("enabled") else ""
    # 2) upload
    up_url = f"{api_base_from_config(cfg)}/api/manuals/{manual_file}/assets"
    try:
        r = http_post_multipart(up_url, asset_path, caption, token)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"uploaded: {r['object_key']} -> {r['public_url']} ({r['size']} bytes, {r['kind']})")
    # 3) print md-insert hint
    print(f"# md 引用: ![{caption or asset_path.stem}]({r['public_url']})")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv))
