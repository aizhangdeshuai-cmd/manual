
from __future__ import annotations
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

from .common import _domain_for_placeholder, _candidate_paths_for_placeholder

# v0.2.4: placeholder markers recognized by scan_recording_placeholders.
#   [SCREENSHOT: <name>]      [SCREENSHOT NEEDED: <name>]
#   [VIDEO: <name>.mp4]       [VIDEO NEEDED: <name>.mp4]
#   [AI ANNOTATE: <name>]     v0.2.4: agent-mediated vision annotation
#
# I11 fix (v0.2.4 audit): name supports multi-segment identifiers like
# "v1.2" or "settings.modal". An optional trailing image/video extension
# (.png / .mp4 / .jpg / .webm / .gif / .mov) is recognized and stripped
# in scan, so mapping keys stay bare ("01-list", "v1.2-heatmap").
_KNOWN_EXTS = ("png", "mp4", "jpg", "jpeg", "webm", "gif", "mov")
_PLACEHOLDER_RE = re.compile(
    r"\[(?P<kind>SCREENSHOT|VIDEO|AI\s+ANNOTATE)"
    r"(?P<needed>\s+NEEDED)?\s*:\s*"
    r"(?P<name>[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]+)*)"
    r"(?:\.(?P<ext>png|mp4|jpg|jpeg|webm|gif|mov))?"
    r"\]"
)


def _strip_ext(name: str) -> str:
    """Strip a trailing image/video extension if present (I11)."""
    parts = name.split(".")
    if len(parts) > 1 and parts[-1].lower() in _KNOWN_EXTS:
        return ".".join(parts[:-1])
    return name


"""
Recording-phase helpers that are intrinsic to the user-manual skill.

This module is intentionally thin. The full Playwright-based recording
("drive a browser, take screenshots, emit videos") lives in the standalone
``recorder`` skill at ``~/.agents/skills/recorder`` — that skill has its
own ``SKILL.md`` and ``recorder_plugin/`` package, and is invoked by the
LLM agent (or by the user) separately.

What stays here, and why:

* ``scan_recording_placeholders`` — finds ``[SCREENSHOT: x]`` and
  ``[VIDEO: x]`` markers in a manual .md. This is a markdown-parsing
  concern; the recorder doesn't own it.
* ``apply_recording_mapping`` — replaces placeholders with real asset
  paths after the recorder has produced them. Also a markdown concern.
* ``build_recorder_template`` + ``_step_template_lines`` etc. — generates
  a recorder-compatible script.json from a manual's placeholders. Uses
  ``manual-config.json`` (project URL, auth env, dev port) which only
  user-manual knows about, so it lives here.
* ``_normalize_mapping_value`` — ``{path, alt}`` -> ``path`` parsing
  for recorder mapping files. Used by ``apply_recording_mapping``.

Subcommands this module NO LONGER provides (moved to recorder skill):
  record-manual, record-and-replace, check-recorder-script
The LLM agent now invokes the recorder skill directly for those flows.
"""
def scan_recording_placeholders(text: str) -> list[dict]:
    """Find all recording placeholders in text.

    v0.2.3: placeholders inside fenced code blocks (```...```) are
    ignored — those are documentation examples showing the syntax,
    not real recording targets.

    v0.2.4: also recognizes `[AI ANNOTATE: <name>]` markers. These are
    deferred to §15 of SKILL.md — the recorder writes a request file,
    the agent fulfills it via its own LLM, recorder applies Pillow
    annotation on re-run of `apply-ai-responses`.

    v0.2.4 (I11): multi-segment placeholder names like "v1.2-heatmap"
    or "settings.modal" are now supported.

    v0.2.4 (G): each result carries a `needed` boolean (true when the
    user wrote `[... NEEDED: x]`, false for the plain `[...: x]` form).
    Downstream missing-list reports use it to distinguish
    `user_declared_needed` (the user explicitly said "this is missing")
    from `no_mapping` (plain placeholder, may or may not be needed).

    Returns list of {"kind": "screenshot"|"video"|"ai_annotate", "name": str,
                    "line": int, "raw": str, "needed": bool}.
    """
    out = []
    in_code = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        for m in _PLACEHOLDER_RE.finditer(line):
            kind_raw = m.group("kind").replace(" ", "").lower()
            if kind_raw == "aiannotate":
                kind = "ai_annotate"
            elif kind_raw == "video":
                kind = "video"
            else:
                kind = "screenshot"
            out.append({
                "kind": kind,
                "name": _strip_ext(m.group("name")),
                "line": i,
                "raw": m.group(0),
                "needed": m.group("needed") is not None,
            })
    return out


def build_recorder_template(
    manual_name: str,
    placeholders: list[dict],
    manual_path: Path | None = None,
    project_root: Path | None = None,
) -> dict:
    """v0.5.0: Generate a recorder script template the LLM agent can fill in.

    v0.2.4 — original: stub with `<TODO: ...>` everywhere; agent had to
    hand-fill every field.

    v0.5.0 — auto-fill from project context when given:
      - `manual_path`: read the .md to extract real per-step captions from
        the task card `### 步骤` sections (replaces `<TODO: caption>`).
      - `project_root`: read `docs/user-manual/manual-config.json` to fill
        `url`, `output_dir`, and infer the starting route from the
        module's first route (via extract-routes.py output if cached,
        else a sensible default per module).

    Still emits `<TODO: ...>` markers where the agent MUST intervene:
      - click selectors (we can't infer from spec text)
      - auth_env names (project-specific; defaults to standard set
        of common ones — LG_USER, LG_PASS, etc., inferred from
        manual_name prefix when possible)

    Returns a dict ready to be `json.dumps()`-ed to a .json file.
    """
    config = _read_manual_config(project_root) if project_root else {}
    domain = _domain_for_placeholder(manual_path, "") if manual_path else "<TODO: domain>"
    # domain from _domain_for_placeholder is e.g. "legal" from "legal-user-manual.md"
    inferred_url = _infer_target_url(config, project_root)
    inferred_route = _infer_starting_route(config, domain)
    inferred_user_env = _infer_auth_env_name(manual_name, "USER")
    inferred_pass_env = _infer_auth_env_name(manual_name, "PASS")
    captions = _extract_step_captions(manual_path) if manual_path else {}

    return {
        "_doc": (
            f"Recorder script template generated for {manual_name} (v0.5.0). "
            f"Auto-filled: url={inferred_url!r}, output_dir inferred from domain, "
            f"step captions from the manual's `### 步骤` sections. "
            "Still TODO: click selectors (the agent must read the actual UI), "
            "and verify auth_env names match this project's credential env vars. "
            "Then run `python3 -m recorder_plugin.cli run <this-file>.json`."
        ),
        "name": manual_name,
        "url": inferred_url,
        "viewport": _infer_viewport(config),
        "output_dir": f"docs/user-manual/screenshots/{domain}/<TODO: subdir>",
        # C fix (v0.2.4 audit): the recorder's resolve_credential() only
        # expands values that start with "$". Bare names like "AUTH_USER"
        # would be passed through as the literal string "AUTH_USER" and
        # submitted to the login form. The $ prefix tells the recorder
        # to look up the env var. Without it, login silently fails.
        # v0.5.0: use module-specific env var names when we can infer them.
        "auth_env": [
            f"${inferred_user_env}",
            f"${inferred_pass_env}",
        ],
        "steps": [
            {"action": "navigate", "url": inferred_route},
            {"action": "wait_for", "strategy": "networkidle"},
            # If we can infer a login step, add a placeholder click for
            # the username / password fields. The agent must fill in the
            # actual selectors.
            {"action": "type",
             "selector": "<TODO: input[name=username], input[type=text], or #username>",
             "value": f"${inferred_user_env}"},
            {"action": "type",
             "selector": "<TODO: input[name=password], input[type=password], or #password>",
             "value": f"${inferred_pass_env}"},
            {"action": "click",
             "selector": "<TODO: button[type=submit], button.login, or [data-test=login-submit]>"},
            {"action": "wait_for", "strategy": "networkidle"},
            *_step_template_lines_v2(placeholders, captions),
        ],
    }


def _step_template_lines_v2(placeholders: list[dict], captions: dict) -> list[dict]:
    """v0.5.0: like _step_template_lines, but uses real captions from
    the manual when available (falls back to <TODO: caption> otherwise).
    """
    out = []
    last_video_started = False
    for p in placeholders:
        if p["kind"] == "screenshot":
            caption = captions.get(p["name"], "<TODO: caption>")
            out.append({
                "action": "screenshot",
                "name": p["name"],
                "annotate": [{"shape": "box", "x": 0, "y": 0, "w": 200, "h": 50,
                              "label": caption}],
            })
        elif p["kind"] == "video":
            if not last_video_started:
                out.append({"action": "video_start", "name": p["name"]})
                last_video_started = True
            else:
                out.append({"action": "video_stop", "name": f"<TODO: previous-video>"})
                out.append({"action": "video_start", "name": p["name"]})
        elif p["kind"] == "ai_annotate":
            out.append({
                "action": "ai_annotate",
                "screenshot": p["name"],
                "prompt": "",
            })
    if last_video_started:
        out.append({"action": "video_stop", "name": "<TODO: last-video>"})
    return out


def _read_manual_config(project_root: Path | None) -> dict:
    """v0.5.0: read manual-config.json if present; return empty dict otherwise.
    Catches all errors (missing file, bad JSON) so this is a safe no-op fallback."""
    if project_root is None:
        return {}
    cfg_path = project_root / "docs" / "user-manual" / "manual-config.json"
    try:
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _infer_viewport(config: dict) -> dict:
    """v2.1.0: pick the recorder viewport from manual-config.json so projects
    can record at their real operator screen size (a.k.a. "full screen").

    Reads ``recording.viewport: {width, height}`` (top-level under the
    config root, not under ``project``). Falls back to 1920x1080 — the
    common desktop logical resolution — so the default is no longer the
    old 1440x900 that produced letterboxed, small-ish videos. Width/height
    must be positive ints; anything else is ignored and the default is used.

    Why a fixed large viewport (not a "maximize real window" mode):
    headless recording with a deterministic viewport is stable across
    re-runs and CI; a headed maximized window drifts when the operator
    switches focus and is implausible in headless jobs. Same approach
    Playwright itself recommends for reproducible video.
    """
    if config:
        vp = config.get("recording", {}).get("viewport") or {}
        w, h = vp.get("width"), vp.get("height")
        if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
            return {"width": w, "height": h}
    return {"width": 1920, "height": 1080}


def _infer_target_url(config: dict, project_root: Path | None) -> str:
    """v0.5.0: build the target URL from manual-config.json.

    Config schema (v2): { "project": { "name": ..., "host": ..., "port": ... } }
    Old schema: { "name": ..., "host": ..., "port": ... }

    Returns a URL like "http://localhost:8080" or "<TODO: target URL>" if
    the config is missing or has placeholders.
    """
    if not config:
        return "<TODO: target URL — set in manual-config.json project.host + port>"
    p = config.get("project") or config  # support both v2 nested and flat
    # v0.5.3: use `or` so None / "" / 0 all fall back to the TODO marker.
    # Without this, `host: null` produced `http://None:8080` and the
    # recorder would try to connect to a non-resolvable hostname.
    host = p.get("host") or "<TODO: host>"
    port = p.get("port") or "<TODO: port>"
    if str(host).startswith("<") or str(port).startswith("<"):
        return f"http://{host}:{port}"
    return f"http://{host}:{port}"


def _infer_starting_route(config: dict, domain: str) -> str:
    """v0.5.0: infer a starting route for the recorder.

    Tries config.project.starting_routes[domain], then falls back to
    a per-domain conventional default (e.g. /contracts for legal,
    /employees for sys). Always returns a path starting with /.
    """
    if config:
        p = config.get("project") or config
        routes = p.get("starting_routes") or {}
        if domain in routes:
            r = routes[domain]
            return r if r.startswith("/") else "/" + r
    # Conventional defaults per domain (covers common cases)
    defaults = {
        "sys":     "/users",
        "system":  "/users",
        "legal":   "/contracts",
        "lg":      "/contracts",
        "esg":     "/dashboard",
        "audit":   "/plans",
        "au":      "/plans",
        "overview": "/dashboard",
    }
    return defaults.get(domain, "/<TODO: starting route>")


def _infer_auth_env_name(manual_name: str, suffix: str) -> str:
    """v0.5.0: infer a sensible env var name for credentials.

    e.g. "legal-user-manual" -> "LEGAL_USER" / "LEGAL_PASS".
    Falls back to "AUTH_USER" / "AUTH_PASS" if the name is too generic.
    """
    stem = manual_name.replace("-user-manual", "").replace("_user_manual", "")
    stem = stem.upper().replace("-", "_").strip("_")
    if not stem or len(stem) < 2:
        return f"AUTH_{suffix}"
    return f"{stem}_{suffix}"


def _extract_step_captions(manual_path: Path) -> dict:
    """v0.5.0: scan the manual for `### 步骤` sections under each task
    card, and return {screenshot_name: caption_string}.

    Heuristic: the first text in each numbered list item under
    `### 步骤` becomes a caption. The mapping screenshot_name -> caption
    is built by taking the i-th step caption and matching it to the
    i-th `[SCREENSHOT: <name>]` placeholder in document order.
    """
    try:
        text = manual_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    placeholders = scan_recording_placeholders(text)
    placeholder_names = [p["name"] for p in placeholders if p["kind"] == "screenshot"]

    # Find each `### 步骤` block and extract numbered items
    captions_per_block: list[list[str]] = []
    in_steps = False
    current_block: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("### 步骤"):
            in_steps = True
            current_block = []
            continue
        if in_steps:
            if s.startswith("###") or s.startswith("##"):
                # End of this block
                if current_block:
                    captions_per_block.append(current_block)
                in_steps = False
                continue
            # Numbered list item: "1. xxx", "2. xxx"
            import re
            m = re.match(r"^(\d+)\.\s+(.+)$", s)
            if m:
                current_block.append(m.group(2).strip())
    if current_block:
        captions_per_block.append(current_block)

    # Flatten (one caption per step in document order, matching the
    # first N screenshot placeholders)
    flat = [cap for block in captions_per_block for cap in block]
    return {name: cap for name, cap in zip(placeholder_names, flat)}


def _step_template_lines(placeholders: list[dict]) -> list[dict]:
    """Convert placeholders into ordered recorder step stubs.

    Each screenshot → one `screenshot` step. Each video → a video_start /
    / video_stop pair surrounding the closest preceding screenshot.
    Each AI ANNOTATE → one `ai_annotate` step (with a `screenshot` field
    pointing at the source PNG; agent fulfills via its own LLM in §15).
    """
    out = []
    last_video_started = False
    for p in placeholders:
        if p["kind"] == "screenshot":
            out.append({
                "action": "screenshot",
                "name": p["name"],
                "annotate": [{"shape": "box", "x": 0, "y": 0, "w": 200, "h": 50,
                              "label": "<TODO: caption>"}],
            })
        elif p["kind"] == "video":
            if not last_video_started:
                out.append({"action": "video_start", "name": p["name"]})
                last_video_started = True
            else:
                # Multiple videos in a row: stop the previous before starting the next
                out.append({"action": "video_stop", "name": f"<TODO: previous-video>"})
                out.append({"action": "video_start", "name": p["name"]})
        elif p["kind"] == "ai_annotate":
            out.append({
                "action": "ai_annotate",
                "screenshot": p["name"],
                "prompt": "",  # F3 fix: agent MUST fill in. Empty prompt -> script runner warns to stderr.
            })
    if last_video_started:
        out.append({"action": "video_stop", "name": "<TODO: last-video>"})
    return out


def _normalize_mapping_value(v) -> tuple[str, str | None]:
    """v0.3.0 (mapping alt field): mapping values can be either a
    bare string (the path; alt defaults to the key) or a dict
    `{path, alt}` for explicit alt text. Returns (path, alt_or_None).
    Raises ValueError on anything else."""
    if isinstance(v, str):
        return v, None
    if isinstance(v, dict) and "path" in v:
        return v["path"], v.get("alt")
    raise ValueError(
        f"invalid mapping value: {v!r} — must be a string path "
        f"or a dict with 'path' (and optional 'alt')"
    )


def apply_recording_mapping(text: str, mapping: dict) -> tuple[str, dict, list, int]:
    """Replace placeholders in text with real asset paths from mapping.

    Recognizes all 3 placeholder kinds (SCREENSHOT, VIDEO, AI ANNOTATE).

    v0.2.4 naming convention for the mapping keys:
      - Plain name (e.g. "01-list") -> replaces [SCREENSHOT: 01-list.*]
        and [VIDEO: 01-list.*] placeholders. Value is the raw .png / .mp4 path.
      - Prefixed name (e.g. "ai-annotated-01-list") -> replaces only
        [AI ANNOTATE: 01-list] placeholders. Value is the *.ai-annotated.png
        path produced by `apply-ai-responses`.

    This separation lets the agent provide different paths for the raw
    screenshot vs. the AI-annotated version. Documented in SKILL.md Sec 15.

    F1 fix: replace ALL occurrences of each placeholder name (not just
    the first). Previous count=1 left 2nd+ same-name placeholders un-replaced.
    F2 fix: AI ANNOTATE placeholders REQUIRE the `ai-annotated-` prefix
    mapping. If only a plain-name mapping exists for the same name, that's
    a config error and the AI ANNOTATE is reported in missing (with
    explicit reason) instead of being silently dropped.

    I11 fix (v0.2.4 audit): multi-segment placeholder names like
    "v1.2-heatmap" are supported. The pattern uses re.escape(name)
    followed by an optional extension.

    I14 fix (v0.2.4 audit): the 4th tuple element is the count of
    placeholder INSTANCES replaced (not unique mapping keys). One
    mapping key may replace 2+ instances if the placeholder appears
    in multiple task cards.

    G fix (v0.2.4 audit): each missing entry now carries a `status`
    field, one of:
      - "no_mapping": placeholder exists in the manual but no mapping
        key was provided. The user wrote plain `[...: x]` (not NEEDED).
      - "user_declared_needed": user wrote `[... NEEDED: x]`, explicitly
        flagging that this placeholder MUST be replaced. The agent loop
        should prioritize these over plain missing.
      - "wrong_mapping_type": AI ANNOTATE placeholder was given a plain
        name mapping key (should be `ai-annotated-` prefixed).

    Returns: (new_text, replaced, missing, replaced_instances)
      - replaced: {mapping_key: real_path} — unique keys that had at
        least one match
      - missing: list of {name, kind, status, reason} for placeholders
        that survived the substitution
      - replaced_instances: total count of placeholder occurrences
        replaced (can exceed len(replaced) if same key appears 2+ times)
    """
    replaced = {}
    missing = []
    replaced_instances = 0
    for key, raw_value in mapping.items():
        # v0.3.0: value can be a string path or a {path, alt} dict
        try:
            real_path, alt_override = _normalize_mapping_value(raw_value)
        except ValueError as e:
            # Surface the bad entry as a missing row so the user sees
            # all mapping problems in one pass instead of one-at-a-time
            missing.append({
                "name": key,
                "kind": "mapping_value",
                "status": "no_mapping",
                "reason": str(e),
            })
            continue
        alt_text = alt_override if alt_override is not None else key
        if key.startswith("ai-annotated-"):
            name = key[len("ai-annotated-"):]
            pattern = re.compile(rf"\[AI\s+ANNOTATE\s*:\s*{re.escape(name)}(?:\.[A-Za-z0-9]+)?\]")
        else:
            name = key
            pattern = re.compile(
                rf"\[(?P<kind>SCREENSHOT|VIDEO)(?:\s+NEEDED)?\s*:\s*{re.escape(name)}(?:\.[A-Za-z0-9]+)?\]"
            )
        if pattern.search(text):
            # v0.3.0: alt text now uses the explicit `alt` field if
            # provided, else falls back to the mapping key (preserves
            # v0.2.x behavior so existing mappings don't need migration).
            new_text, n = pattern.subn(f"![{alt_text}]({real_path})", text)  # count=0: replace all
            text = new_text
            replaced[key] = real_path
            replaced_instances += n
    remaining = scan_recording_placeholders(text)
    for p in remaining:
        if p["kind"] == "ai_annotate":
            prefixed_key = f"ai-annotated-{p['name']}"
            # F2 fix: explicit missing detection for AI ANNOTATE
            if prefixed_key in mapping:
                continue
            if p["name"] in mapping:
                missing.append({
                    "name": p["name"],
                    "kind": "ai_annotate",
                    "status": "wrong_mapping_type",
                    "reason": (f"AI ANNOTATE requires mapping key "
                               f"'ai-annotated-{p['name']}', not plain "
                               f"'{p['name']}'. Plain key replaces "
                               f"[SCREENSHOT:] only."),
                })
            else:
                missing.append({
                    "name": p["name"],
                    "kind": "ai_annotate",
                    "status": "no_mapping",
                    "reason": (f"No mapping entry for this AI ANNOTATE. "
                               f"Add 'ai-annotated-{p['name']}' to mapping."),
                })
        else:
            if p["name"] not in mapping:
                # G fix: distinguish no_mapping from user_declared_needed
                status = "user_declared_needed" if p["needed"] else "no_mapping"
                missing.append({
                    "name": p["name"],
                    "kind": p["kind"],
                    "status": status,
                    "reason": (f"No mapping entry for this "
                               f"{p['kind']} placeholder."),
                })
    return text, replaced, missing, replaced_instances


# v2.1.0: recorder (recorder/SKILL.md) synthesizes a narrated video and
# keeps the PRE-narration silent copy as `<name>.silent.mp4` next to it.
# The silent copy is a backup, never referenced by any manual .md (only
# the narrated `<name>.mp4` is) — but it's written into screenshots/ and
# gets committed. The ehr manual shipped 6 silent copies (~2.8MB of pure
# dead weight in git). This helper prunes orphan .silent.mp4 files whose
# narrated sibling is NOT referenced by any of the given manual .md files.
#
# "Referenced" = ANY manual .md contains the narrated sibling's filename
# (basename) — we match on basename because manuals reference assets via
# relative paths like `../screenshots/x/x.mp4` and we only need to know
# that the narrated copy is in use, which implies its silent backup is
# the one to prune. If the narrated sibling itself is missing or
# unreferenced, the silent copy is NOT pruned (it might be all the user
# has) — we surface it as `keep_orphan`.
_SILENT_RE = re.compile(r"^(?P<stem>.+)\.silent\.mp4$")


def prune_silent_backups(
    screenshots_dir: Path,
    manual_paths: list[Path],
    apply: bool = False,
) -> dict:
    """Find and (optionally) delete `.silent.mp4` files under
    ``screenshots_dir`` whose narrated sibling is referenced by one of
    ``manual_paths``.

    A silent file ``<stem>.silent.mp4`` is pruned iff:
      - its narrated sibling ``<stem>.mp4`` EXISTS on disk, AND
      - some manual .md references that sibling by basename.

    Silent files whose narrated sibling is missing OR unreferenced are
    reported as ``keep_orphan`` (left on disk) — pruning those could
    delete the only copy.

    Args:
        screenshots_dir: directory tree holding the .silent.mp4 files
            (and their narrated siblings).
        manual_paths: manual .md files whose references drive the
            "is the narrated copy in use?" decision.
        apply: False (default) = dry-run, just report. True = unlink
            the prunable files.

    Returns a report dict:
        ``prunable``       — list of .silent.mp4 paths safe to delete
        ``keep_orphan``    — silent paths kept (no narrated sibling in use)
        ``deleted``        — actually deleted (only when apply=True)
        ``bytes_freed``    — bytes unlinked (only when apply=True)
    """
    screenshots_dir = Path(screenshots_dir).resolve()
    if not screenshots_dir.is_dir():
        raise FileNotFoundError(f"screenshots dir not found: {screenshots_dir}")

    # Collect every manual's text once; reference set = basenames of any
    # `something.mp4` (silent paths can't be referenced because the
    # recorder never names an output `.silent.mp4`).
    referenced: set[str] = set()
    for mp in manual_paths:
        mp = Path(mp)
        if not mp.exists():
            continue
        try:
            txt = mp.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            txt = mp.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"[\w./-]+\.mp4(?=\s|\)|\]|$)", txt):
            referenced.add(Path(m.group(0)).name)

    prunable: list[str] = []
    keep_orphan: list[str] = []
    deleted: list[str] = []
    bytes_freed = 0

    for candidate in sorted(screenshots_dir.rglob("*.silent.mp4")):
        m = _SILENT_RE.match(candidate.name)
        if not m:
            continue
        narrated = candidate.with_name(f"{m.group('stem')}.mp4")
        narrated_in_use = narrated.exists() and narrated.name in referenced
        if narrated_in_use:
            prunable.append(str(candidate))
        else:
            keep_orphan.append(str(candidate))

    if apply:
        for p in prunable:
            try:
                sz = Path(p).stat().st_size
                Path(p).unlink()
                deleted.append(p)
                bytes_freed += sz
            except OSError as e:
                print(f"warn: could not delete {p}: {e}", file=sys.stderr)

    return {
        "prunable": prunable,
        "keep_orphan": keep_orphan,
        "deleted": deleted,
        "bytes_freed": bytes_freed,
    }
