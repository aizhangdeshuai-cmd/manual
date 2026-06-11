-- user_manual schema
-- Idempotent: drop+recreate on init. Use cautiously in prod.

DROP TABLE IF EXISTS manual_assets CASCADE;
DROP TABLE IF EXISTS manuals CASCADE;
DROP TABLE IF EXISTS modules CASCADE;

CREATE TABLE modules (
    id SERIAL PRIMARY KEY,
    code TEXT UNIQUE NOT NULL,                -- e.g. "FR", "LG"
    name TEXT NOT NULL,                       -- e.g. "Finance"
    description TEXT,
    order_index INT NOT NULL DEFAULT 0
);

CREATE TABLE manuals (
    id SERIAL PRIMARY KEY,
    file TEXT UNIQUE NOT NULL,                -- e.g. "user-manual.md" (logical key, also file:// mode)
    module_id INT REFERENCES modules(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT,
    order_index INT NOT NULL DEFAULT 999,
    version TEXT NOT NULL,
    version_date DATE,
    body_md TEXT NOT NULL,                    -- strip frontmatter
    raw_md TEXT,                              -- 带 frontmatter 原文(可选)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_manuals_module_order ON manuals(module_id, order_index);

CREATE TABLE manual_assets (
    id SERIAL PRIMARY KEY,
    manual_id INT NOT NULL REFERENCES manuals(id) ON DELETE CASCADE,
    object_key TEXT UNIQUE NOT NULL,          -- S3 路径
    original_name TEXT NOT NULL,
    kind TEXT NOT NULL,                       -- "image" | "video" | "other"
    mime_type TEXT,
    size_bytes BIGINT,
    caption TEXT,
    width INT,
    height INT,
    duration_sec NUMERIC,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_assets_manual ON manual_assets(manual_id);
