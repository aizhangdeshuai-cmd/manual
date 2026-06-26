"""user-manual skill — manual_helper package.

Public API is re-exported at the package level so existing callers
(``import manual_helper; manual_helper.html_on_disk_version(...)``)
keep working. Implementation modules are also importable as
``manual_helper.html``, ``manual_helper.recording``, etc., for
internal use and unit testing.

Module layout (each file 50-1300 lines, was a single 3700-line file):

  common        — shared constants, ET timestamp, template strings
  init          — single-manual init + project bootstrap (_detect_project_layout)
  readiness     — recording-phase preflight checks
  config        — manual-config.json / personas.json validation
  artifacts     — scan-artifacts, parse-citations, diff-artifacts, fill-citation-shas
  html          — bundled template version, standalone build, manual-index writer
  extract       — extract-tasks/fields/routes/roles/openapi CLI wrappers
  recording     — placeholder scan/apply, recorder template builder (recorder CLI subcommands live in the recorder skill)
  db            — db-backend helpers (init-db, upsert-manual, upload-asset)
  cli           — main() entry + per-subcommand dispatch
"""
from __future__ import annotations

# common
from .common import (
    ET,
    HTML_VERSION_RE,
    SUPERPOWERS_KINDS,
    TEMPLATE_HTML_PATH,
    CITATIONS_BLOCK,
    DEFAULT_CONFIG,
    DEFAULT_CONFIG_LINES,
    TEMPLATE,
    now_et,
)

# init
from .init import (
    init,
    init_skill,
    _detect_project_layout,
    _init_skill_scaffold,
    RecordingBlockedError,
    _is_dev_server_red_only,
    _auto_install_recorder_deps,
)

# readiness
from .readiness import (
    check_recording_readiness,
    _print_recording_readiness_banner,
)

# Pure path helpers live in common (no circular dep)
from .common import (
    _domain_for_placeholder,
    _candidate_paths_for_placeholder,
)

# config
from .config import validate_config

# artifacts
from .artifacts import (
    scan_artifacts,
    parse_citations,
    diff_artifacts,
    fill_citation_shas,
    _cmd_fill_citation_shas,
    _render_filled_citations_table,
    _split_table_row,
    _is_separator_row,
    _normalize_artifact_path,
    _short_hash,
    _extract_title,
    _infer_project_root,
)

# html
from .html import (
    html_template_version,
    html_on_disk_version,
    regenerate_html_if_stale,
    build_standalone,
    write_index,
    _parse_frontmatter,
    _extract_title_from_md,
    _read_html_version,
    _slugify_for_id,
    _convert_video_links_to_html,
    _inline_assets_to_data_urls,
)

# extract
from .extract import (
    cmd_extract_tasks,
    cmd_extract_fields,
    cmd_extract_routes,
    cmd_extract_roles,
    cmd_extract_openapi,
)

# recording — only the user-manual-side helpers stay here. The recorder
# skill (recorder-manual, record-and-replace, check-recorder-script) lives
# at ~/.agents/skills/recorder and is invoked separately.
from .recording import (
    scan_recording_placeholders,
    build_recorder_template,
    _step_template_lines_v2,
    _read_manual_config,
    _infer_target_url,
    _infer_starting_route,
    _infer_auth_env_name,
    _infer_viewport,
    _extract_step_captions,
    _step_template_lines,
    _normalize_mapping_value,
    apply_recording_mapping,
)

# db
from .db import (
    find_config,
    load_config,
    api_base_from_config,
    read_md_split,
    http_post_json,
    http_post_multipart,
    cmd_read_config,
    cmd_init_db,
    cmd_upsert_manual,
    cmd_upload_asset,
)

# cli
from .cli import main


__all__ = [
    # common
    "ET", "HTML_VERSION_RE", "SUPERPOWERS_KINDS", "TEMPLATE_HTML_PATH",
    "CITATIONS_BLOCK", "DEFAULT_CONFIG", "DEFAULT_CONFIG_LINES", "TEMPLATE",
    "now_et",
    # init
    "init", "init_skill", "_detect_project_layout", "_init_skill_scaffold",
    "RecordingBlockedError", "_is_dev_server_red_only", "_auto_install_recorder_deps",
    # readiness
    "check_recording_readiness", "_print_recording_readiness_banner",
    "_domain_for_placeholder", "_candidate_paths_for_placeholder",
    # config
    "validate_config",
    # artifacts
    "scan_artifacts", "parse_citations", "diff_artifacts", "fill_citation_shas",
    "_cmd_fill_citation_shas", "_render_filled_citations_table",
    "_split_table_row", "_is_separator_row", "_normalize_artifact_path",
    "_short_hash", "_extract_title", "_infer_project_root",
    # html
    "html_template_version", "html_on_disk_version", "regenerate_html_if_stale",
    "build_standalone", "write_index",
    "_parse_frontmatter", "_extract_title_from_md", "_read_html_version",
    "_slugify_for_id", "_convert_video_links_to_html", "_inline_assets_to_data_urls",
    # extract
    "cmd_extract_tasks", "cmd_extract_fields", "cmd_extract_routes",
    "cmd_extract_roles", "cmd_extract_openapi",
    # recording (user-manual-side only; recorder skill lives at ~/.agents/skills/recorder)
    "scan_recording_placeholders", "build_recorder_template",
    "_step_template_lines_v2", "_read_manual_config",
    "_infer_target_url", "_infer_starting_route", "_infer_auth_env_name",
    "_infer_viewport",
    "_extract_step_captions", "_step_template_lines",
    "_normalize_mapping_value", "apply_recording_mapping",
    # db
    "find_config", "load_config", "api_base_from_config", "read_md_split",
    "http_post_json", "http_post_multipart",
    "cmd_read_config", "cmd_init_db", "cmd_upsert_manual", "cmd_upload_asset",
    # cli
    "main",
]
