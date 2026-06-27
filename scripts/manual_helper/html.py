
from __future__ import annotations
import base64
import json
import os
import shutil
import sys
from pathlib import Path

from .common import (
    HTML_VERSION_RE,
    TEMPLATE_HTML_PATH,
    now_et,
)

def _read_html_version(text: str) -> int | None:
    match = HTML_VERSION_RE.search(text)
    return int(match.group(1)) if match else None


def html_template_version() -> int:
    if not TEMPLATE_HTML_PATH.exists():
        raise FileNotFoundError(
            f"bundled HTML template missing at {TEMPLATE_HTML_PATH}"
        )
    version = _read_html_version(TEMPLATE_HTML_PATH.read_text(encoding="utf-8"))
    if version is None:
        raise ValueError(
            f"template at {TEMPLATE_HTML_PATH} has no "
            f"<!-- user-manual-dashboard-version: N --> marker"
        )
    return version


def html_on_disk_version(html_path: Path) -> int:
    """Read the version marker from a user-generated HTML file on disk.

    Mirrors html_template_version() but for the file the user/skill wrote
    (e.g. <project>/docs/user-manual/user-manual.html), not the bundled
    template. Use to decide whether regenerate_html_if_stale() will copy.

    Raises FileNotFoundError if html_path is missing, ValueError if the file
    exists but has no version marker.
    """
    if not html_path.exists():
        raise FileNotFoundError(f"html file not found: {html_path}")
    version = _read_html_version(html_path.read_text(encoding="utf-8"))
    if version is None:
        raise ValueError(
            f"{html_path} has no <!-- user-manual-dashboard-version: N --> marker"
        )
    return version


def regenerate_html_if_stale(html_path: Path) -> str:
    template_version = html_template_version()
    html_path.parent.mkdir(parents=True, exist_ok=True)

    if not html_path.exists():
        shutil.copyfile(TEMPLATE_HTML_PATH, html_path)
        return "created"

    existing_version = _read_html_version(html_path.read_text(encoding="utf-8"))
    if existing_version is None or existing_version < template_version:
        shutil.copyfile(TEMPLATE_HTML_PATH, html_path)
        return "regenerated"

    return "unchanged"


def regenerate_standalone_if_stale(
    html_out_path: Path,
    md_paths: list[Path],
    *,
    template_path: Path | None = None,
) -> str:
    """v1.4.0: rebuild the inlined standalone HTML when any of these change:
      1. The bundled template version is newer than what was last inlined
         (marker in <!-- INLINE: standalone build, do not edit by hand -->).
      2. Any source .md has been modified after the inlined HTML.
      3. The inlined HTML is missing.

    v1.3.1 fix: previously the viewer template's `extractTitle()` regex
    couldn't match the inline markdown because the leading `<script>` tag
    in build_standalone wrote a newline before the YAML frontmatter
    (`text.startsWith("---")` was always false; title fell through to
    filename). v2.3.1 fixed this by writing a `data-title` attribute on
    each inline `<script>` block. But ehr 2026-06 ships a standalone
    HTML built BEFORE that fix — the inlined blocks have no
    `data-title`, so dashboard cards show `user-manual.md` instead of
    the Chinese frontmatter title. The wrapper template's version
    marker is the NEW version (because the wrapper is regenerated
    separately), but the inlined body is STALE.

    The fix: this function checks the inlined HTML for the data-title
    attribute as a staleness signal. If absent, force a rebuild
    regardless of the wrapper version.
    """
    if template_path is None:
        template_path = TEMPLATE_HTML_PATH
    template_version = html_template_version()
    html_out_path.parent.mkdir(parents=True, exist_ok=True)
    if not html_out_path.exists():
        build_standalone(template_path, html_out_path, md_paths)
        return "created"
    on_disk = html_out_path.read_text(encoding="utf-8")
    # Stale if the wrapper version is older than the template.
    wrapper_version = _read_html_version(on_disk)
    wrapper_stale = (
        wrapper_version is None or wrapper_version < template_version
    )
    # Stale if any source .md is newer than the inlined HTML.
    inlined_mtime = html_out_path.stat().st_mtime
    md_stale = False
    for p in md_paths:
        if p.exists() and p.stat().st_mtime > inlined_mtime:
            md_stale = True
            break
    # v1.3.1: stale if the inlined <script type="text/markdown"> blocks
    # lack `data-title` (the viewer template was upgraded to write it;
    # pre-upgrade builds produced inlined blocks WITHOUT it, and the
    # wrapper template alone can't recover because the data lives in
    # the inlined <script>, not the wrapper). We use a regex anchored
    # to the inline block opening tag — a stray `data-title="${...}"`
    # in the viewer template's own code (e.g. the dashboard card render)
    # should NOT count as a satisfied contract.
    import re as _re
    inlined_stale = not _re.search(
        r'<script type="text/markdown"[^>]*\bdata-title="',
        on_disk,
    )
    if wrapper_stale or md_stale or inlined_stale:
        build_standalone(template_path, html_out_path, md_paths)
        reasons = []
        if wrapper_stale:
            reasons.append(f"wrapper v{wrapper_version} < template v{template_version}")
        if md_stale:
            reasons.append("source .md newer than inlined HTML")
        if inlined_stale:
            reasons.append("inlined <script> blocks lack data-title (v1.3.1+ viewer fix not yet inlined)")
        return "regenerated: " + "; ".join(reasons)
    return "unchanged"


# ---------- CLI ----------

def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML-ish frontmatter (--- ... ---) from body. Returns (meta, body).
    Tolerant: if no frontmatter, returns ({}, text).
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm_block = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")
    meta = {}
    for line in fm_block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


def _extract_title_from_md(text: str, fallback: str) -> str:
    """Title resolution order: frontmatter title: > first H1 > filename fallback."""
    meta, body = _parse_frontmatter(text)
    if meta.get("title"):
        return meta["title"]
    for line in body.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return fallback


def write_index(html_dir: Path, md_paths: list[Path]) -> Path:
    """Write manual-index.json into html_dir. Returns the path written."""
    manuals = []
    for p in md_paths:
        if not p.exists():
            print(f"warn: {p} does not exist, skipping", file=sys.stderr)
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = p.read_text(encoding="utf-8", errors="replace")
        meta, _ = _parse_frontmatter(text)
        rel = p.resolve().relative_to(html_dir.resolve())
        # Use forward slashes for web-safety
        rel_str = str(rel).replace(os.sep, "/")
        title = meta.get("title") or _extract_title_from_md(text, p.stem)
        manuals.append({
            "file": rel_str,
            "title": title,
            "module": meta.get("module", ""),
            "description": meta.get("description", ""),
            "order": int(meta["order"]) if meta.get("order", "").isdigit() else 999,
        })
    manuals.sort(key=lambda m: (m["order"], m["title"]))
    out = {
        "version": 1,
        "generated": now_et(),
        "manuals": manuals,
    }
    out_path = html_dir / "manual-index.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def _slugify_for_id(name: str) -> str:
    """Make a safe DOM id from a filename. e.g. '财务-使用手册.md' -> 'md-xn--wgv4a9ih6f'."""
    import re as _re
    import unicodedata
    # Try to keep ASCII by NFKD-normalizing and dropping non-ASCII
    base = name.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    nfkd = unicodedata.normalize("NFKD", base)
    ascii_form = nfkd.encode("ascii", "ignore").decode("ascii")
    safe = _re.sub(r"[^A-Za-z0-9_-]", "-", ascii_form).strip("-")
    if not safe:
        # Pure non-ASCII: just hex-encode the original
        safe = "x" + "".join(f"{ord(c):x}" for c in base)[:32]
    return safe



def _convert_video_links_to_html(text: str) -> str:
    """v1.0.1: convert markdown `[VIDEO: title](path.mp4)` to
    a playable HTML5 `<video controls>` element. Mirrors the
    runtime `convertVideoLinksInMd()` in templates/user-manual.html
    so that build-standalone output contains the <video> tag
    literally (no JS required to see the player).
    """
    import re as _re
    pat = _re.compile(
        r'\[VIDEO:\s*([^\]]+)\]\(([^)\s]+\.(?:mp4|webm|mov))'
        r'(\s+"[^"]*")?\)',
        _re.IGNORECASE,
    )
    def _sub(m):
        alt = m.group(1).replace('"', "&quot;")
        src = m.group(2)
        return (
            '<video controls preload="metadata" playsinline '
            'style="max-width:100%;height:auto;display:block;margin:8px 0">'
            f'<source src="{src}" type="video/mp4">'
            '\u672a\u652f\u6301\u89c6\u9891\u6807\u7b7e'
            '</video>'
        )
    return pat.sub(_sub, text)



def _inline_assets_to_data_urls(text, md_path):
    """v1.0.1: for build_standalone output (file:// mode), inline
    all referenced PNG / MP4 / JPG files as base64 `data:` URLs so
    the rendered HTML works when double-clicked (browsers refuse
    to load relative-path images in file:// mode for security).
    """
    import re as _ire, base64
    md_dir = md_path.parent
    IMG_EXTS = ("png", "jpg", "jpeg", "gif", "webp")
    VID_EXTS = ("mp4", "webm", "mov")
    ALL_EXTS = IMG_EXTS + VID_EXTS

    def _resolve(rel_path):
        if rel_path.startswith(("data:", "http://", "https://", "#")):
            return None
        clean = rel_path.split("?")[0].split("#")[0]
        if not any(clean.lower().endswith("." + e) for e in ALL_EXTS):
            return None
        candidates = [
            md_dir / clean,
            md_dir / "screenshots" / Path(clean).name,
            md_dir / "videos" / Path(clean).name,
            md_dir / "assets" / Path(clean).name,
        ]
        for c in candidates:
            try:
                resolved = c.resolve()
            except OSError:
                continue
            if resolved.exists() and resolved.is_file():
                try:
                    data = resolved.read_bytes()
                except OSError:
                    continue
                if clean.lower().endswith(".png"):
                    mime = "image/png"
                elif clean.lower().endswith((".jpg", ".jpeg")):
                    mime = "image/jpeg"
                elif clean.lower().endswith(".gif"):
                    mime = "image/gif"
                elif clean.lower().endswith(".webp"):
                    mime = "image/webp"
                elif clean.lower().endswith(".mp4"):
                    mime = "video/mp4"
                elif clean.lower().endswith(".webm"):
                    mime = "video/webm"
                else:
                    mime = "video/quicktime"
                return "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")
        return None

    # 1) Markdown image refs: ![alt](path)
    def _md(m):
        prefix_b, alt, paren_b, src, paren_e = (
            m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        )
        data_url = _resolve(src)
        if data_url is None:
            return m.group(0)
        return prefix_b + alt + paren_b + data_url + paren_e
    text = _ire.sub(
        r"(!\[)([^\]]*)(\]\()([^\s)]+)(\))",
        _md, text,
    )

    # 2) Tag refs: <source src="path">, <video src="path">, <img src="path">
    def _tag(m):
        full = m.group(0)
        sm = _ire.search(r'src="([^"]+)"', full)
        if not sm:
            return full
        src = sm.group(1)
        data_url = _resolve(src)
        if data_url is None:
            return full
        return full.replace('src="' + src + '"', 'src="' + data_url + '"')
    text = _ire.sub(
        r"<(?:source|video|img)\b[^>]*?\bsrc=\"[^\"]+\"[^>]*>",
        _tag, text,
    )

    # 3) v1.0.2 fix: [VIDEO: title](path.mp4) markdown refs. The template
    # converts these to <video><source src="path"> at runtime in the
    # browser, AFTER the inliner runs. If we don't catch them here, the
    # resulting HTML has <source src="path.mp4"> with a relative path
    # that file:// refuses to load → video shows as broken player.
    def _md_video(m):
        prefix_b, alt, paren_b, src, paren_e = (
            m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        )
        data_url = _resolve(src)
        if data_url is None:
            return m.group(0)
        return prefix_b + alt + paren_b + data_url + paren_e
    text = _ire.sub(
        r"(\[VIDEO:\s*)([^\]]*)(\]\()([^\s)]+\.(?:mp4|webm|mov))(\))",
        _md_video, text,
    )
    return text





def _extract_title_from_markdown(text: str) -> str:
    """v2.3.1: pull the title out of a markdown file's YAML frontmatter.

    Used by `build_standalone()` to write a `data-title` attribute on the
    inline `<script type="text/markdown">` block, so the viewer can show
    the Chinese title in dashboard cards without re-running its own regex
    over `textContent` (which starts with a leading \n after
    build-standalone writes the opening `<script>` tag, breaking
    `extractTitle()`'s `^---` anchor).

    Falls back to first H1, then to empty string.
    Never returns the filename — that's the viewer's job, not ours.
    """
    import re as _re
    t = text.lstrip()
    m = _re.match(r"^---\s*\n([\s\S]*?)\n---", t)
    if m:
        for line in m.group(1).split("\n"):
            line = line.strip()
            if line.startswith("title:"):
                return line[len("title:"):].strip().strip('"').strip("'")
    for line in t.split("\n"):
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return ""


def build_standalone(html_template_path: Path, html_out_path: Path, md_paths: list[Path]) -> Path:
    """Read the html template, inline all .md files as <script> blocks, write out.

    The output html reads from the inline <script> blocks first (so file:// works),
    falling back to fetch() (so it still works under HTTP if you want to add more
    manuals later).
    """
    html = html_template_path.read_text(encoding="utf-8")
    # Preserve whatever version the template has — don't force a number here,
    # that would silently regress the version on every build.
    # Insert inline markdown blocks right after <body> opens — must be BEFORE
    # the IIFE boot script that reads them. <body> opening tag is more
    # reliable than </head> across templating variations.
    body_open = html.find("<body>")
    if body_open < 0:
        body_open = html.find("<body ")
    if body_open < 0:
        raise ValueError("html template has no <body>")
    body_open_end = html.find(">", body_open) + 1  # position right after >

    inline_blocks = []
    for p in md_paths:
        if not p.exists():
            print(f"warn: {p} not found, skipping", file=sys.stderr)
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = p.read_text(encoding="utf-8", errors="replace")
        # v1.0.1: pre-render [VIDEO: x](path) -> <video> so the
        # build-standalone output has the <video> tag literally
        # (no JS needed to see the player). Mirrors the runtime
        # convertVideoLinksInMd() in the viewer template.
        text = _convert_video_links_to_html(text)
        # v1.0.1: inline PNG/MP4 references as data: URLs so the
        # standalone .html works under file:// (browsers block
        # relative-path images there). Runs AFTER video conversion
        # so <source src=...> tags from _convert_video_links_to_html
        # also get inlined.
        text = _inline_assets_to_data_urls(text, p)
        # Escape </script> to avoid breaking out of the script tag
        text = text.replace("</script>", "<\\/script>")
        sid = _slugify_for_id(p.name)
        rel = p.name  # already relative to html dir (caller responsibility)
        # v2.3.1: pre-extract the title so the viewer doesn't have to
        # regex over the inlined textContent. See _extract_title_from_markdown.
        title = _extract_title_from_markdown(text)
        title_attr = f' data-title="{title}"' if title else ""
        inline_blocks.append(
            f'<script type="text/markdown" data-file="{rel}" id="md-{sid}"{title_attr}>\n'
            f'{text}\n'
            f'</script>'
        )

    # Insert right after <body>, before the IIFE script
    insertion = "\n<!-- INLINE: standalone build, do not edit by hand -->\n" + "\n".join(inline_blocks) + "\n"
    html = html[:body_open_end] + insertion + html[body_open_end:]

    html_out_path.write_text(html, encoding="utf-8")
    return html_out_path




