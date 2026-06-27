
from __future__ import annotations
import json
import sys
from pathlib import Path

from .common import now_et

# Bring in everything cli.py needs. We use importlib to load submodules
# by file path, because `from . import init` would resolve to the
# package-level `init` function (re-exported by __init__.py) rather than
# the actual module — a name shadowing issue that's hard to fix otherwise.
import importlib
import importlib.util as _importlib_util
import sys as _sys

def _load_submodule(name: str):
    spec = _importlib_util.find_spec(f"manual_helper.{name}")
    mod = importlib.util.module_from_spec(spec)
    _sys.modules[f"manual_helper.{name}"] = mod  # cache so re-imports are cheap
    spec.loader.exec_module(mod)
    return mod

_artifacts = _load_submodule("artifacts")
_config = _load_submodule("config")
_db = _load_submodule("db")
_extract = _load_submodule("extract")
_html = _load_submodule("html")
_init_mod = _load_submodule("init")
_readiness = _load_submodule("readiness")
_recording = _load_submodule("recording")

# Re-bind names cli.main() actually uses. Doing it explicitly (vs.
# `from . import *`) keeps lint and tracebacks friendly.
init = _init_mod.init
RecordingBlockedError = _init_mod.RecordingBlockedError
init_skill = _init_mod.init_skill
_detect_project_layout = _init_mod._detect_project_layout
check_recording_readiness = _readiness.check_recording_readiness
_print_recording_readiness_banner = _readiness._print_recording_readiness_banner
validate_config = _config.validate_config
scan_artifacts = _artifacts.scan_artifacts
parse_citations = _artifacts.parse_citations
diff_artifacts = _artifacts.diff_artifacts
_cmd_fill_citation_shas = _artifacts._cmd_fill_citation_shas
html_template_version = _html.html_template_version
html_on_disk_version = _html.html_on_disk_version
regenerate_html_if_stale = _html.regenerate_html_if_stale
build_standalone = _html.build_standalone
write_index = _html.write_index
cmd_extract_tasks = _extract.cmd_extract_tasks
cmd_extract_fields = _extract.cmd_extract_fields
cmd_extract_routes = _extract.cmd_extract_routes
cmd_extract_roles = _extract.cmd_extract_roles
cmd_extract_openapi = _extract.cmd_extract_openapi
cmd_read_config = _db.cmd_read_config
cmd_init_db = _db.cmd_init_db
cmd_upsert_manual = _db.cmd_upsert_manual
cmd_upload_asset = _db.cmd_upload_asset
prune_silent_backups = _recording.prune_silent_backups
auto_promote_annotated_paths = _recording.auto_promote_annotated_paths
_resolve_annotated_sibling = _recording._resolve_annotated_sibling
write_recording_manifest = _recording.write_recording_manifest


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("--help", "-h", "help"):
        # Print the package-level docstring (full subcommand list) when
        # --help is requested. The cli module's own docstring is just
        # the dispatch table, not user-facing help.
        import manual_helper as _pkg
        help_text = _pkg.__doc__ or "manual_helper: no help available; see SKILL.md."
        print(help_text)
        return 0 if len(argv) >= 2 else 2

    cmd = argv[1]

    if cmd == "now-et":
        print(now_et())
        return 0

    if cmd == "init":
        if len(argv) != 3:
            print("usage: manual_helper.py init <md-path>", file=sys.stderr)
            return 2
        target = Path(argv[2])
        created = init(target)
        print(f"{'created' if created else 'exists'}: {target}")
        return 0

    if cmd == "init-skill":
        # v1.0.0: BREAKING. --allow-blocked removed. A manual without
        # real screenshots and videos is not a valid deliverable. If
        # the recording phase cannot run, the LLM must fix the
        # environment (start dev server, install deps) and re-run.
        # --no-install is kept for CI environments that manage deps
        # via other channels.
        auto_install = "--no-install" not in argv
        if "--allow-blocked" in argv:
            print("ERROR: --allow-blocked was removed in v1.0.0.", file=sys.stderr)
            print("  The skill now requires real screenshots and videos.", file=sys.stderr)
            print("  Fix the recording-readiness failures and re-run.", file=sys.stderr)
            return 2
        positionals = [a for a in argv[2:] if not a.startswith("--")]
        proj_root = Path(positionals[0]) if positionals else Path.cwd()
        try:
            result = init_skill(
                proj_root,
                auto_install=auto_install,
            )
        except FileNotFoundError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        except RecordingBlockedError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            print("", file=sys.stderr)
            print("  The recording phase (§14) cannot run.", file=sys.stderr)
            print("  The skill v1.0.0 no longer supports a draft-only deliverable.", file=sys.stderr)
            print("  Options:", file=sys.stderr)
            print("    1. Fix the issues above and re-run `init-skill`", file=sys.stderr)
            print("    2. Re-run with --no-install if you manage deps via CI", file=sys.stderr)
            return 2
        print(f"project root: {proj_root}")
        for p in result["created"]:
            print(f"  created: {p}")
        for p in result["skipped"]:
            print(f"  skipped (exists): {p}")
        if "personas_required" in result:
            print(f"  personas: {result['personas_required']} (present)")
        if not result["created"]:
            print("(nothing to do -- already initialized)")
        # v0.4.0: print the readiness badge (OK/WARN/BLOCKED). Default
        # behavior is to fail if BLOCKED (see RecordingBlockedError above).
        _print_recording_readiness_banner(result.get("recording_readiness", {}))
        if result.get("auto_install_attempted"):
            if result.get("auto_install_ok"):
                print("", file=sys.stderr)
                print("✅ auto-install completed; recording phase is ready.", file=sys.stderr)
            else:
                print("", file=sys.stderr)
                print("⚠️  auto-install could not complete; see messages above.", file=sys.stderr)
        # v0.5.0: auto-regenerate <proj>/docs/user-manual/user-manual.html
        # if the shipped template is newer than what is on disk. Keeps
        # the viewer (TOC fix, etc.) in sync without forcing the user
        # to remember to re-build after a skill upgrade. Failures here
        # are non-fatal: the LLM may be running on a read-only project
        # root, or the project may not have a user-manual.html yet.
        try:
            html_target = proj_root / "docs" / "user-manual" / "user-manual.html"
            regen_status = regenerate_html_if_stale(html_target)
            if regen_status == "regenerated":
                print(f"  viewer: regenerated {html_target} (template v{html_template_version()})", file=sys.stderr)
            elif regen_status == "created":
                print(f"  viewer: created {html_target} (template v{html_template_version()})", file=sys.stderr)
        except (FileNotFoundError, ValueError, OSError) as e:
            print(f"  viewer: auto-regen skipped ({type(e).__name__}: {e})", file=sys.stderr)
        return 0

    if cmd == "check-recording-readiness":
        # parse the positional project root (skip flags like --json);
        # the old len(argv)==3 guard ignored an explicitly-passed
        # root whenever any flag (e.g. --json) was present and fell
        # back to cwd, which silently checked the wrong project.
        _pos = [a for a in argv[2:] if not a.startswith("--")]
        proj_root = Path(_pos[0]) if _pos else Path.cwd()
        readiness = check_recording_readiness(proj_root)
        if "--json" in argv:
            print(json.dumps(readiness, ensure_ascii=False, indent=2))
        else:
            badge = {"green": "✅ GREEN", "yellow": "🟡 WARNING", "red": "🔴 BLOCKED"}[readiness["status"]]
            print(f"=== Recording Phase Readiness ({badge}) ===")
            for c in readiness["checks"]:
                icon = {"OK": "✅", "WARN": "⚠️ ", "FAIL": "❌"}[c["status"]]
                print(f"  {icon}  {c['name']}: {c['detail']}")
                if c["fix"]:
                    print(f"        → {c['fix']}")
            print()
            print(f"  {readiness['summary']}")
        # 0 = green, 1 = yellow, 2 = red. Useful for CI.
        return {"green": 0, "yellow": 1, "red": 2}[readiness["status"]]

    if cmd == "validate-config":
        proj_root = Path(argv[2]) if len(argv) == 3 else Path.cwd()
        result = validate_config(proj_root)
        if "--json" in argv:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if result["errors"]:
                print("ERRORS:")
                for e in result["errors"]:
                    print(f"  - {e}")
            if result["warnings"]:
                print("WARNINGS:")
                for w in result["warnings"]:
                    print(f"  - {w}")
            if result["ok"]:
                print("OK: manual-config.json + personas.json valid.")
                print(f"     personas: {len(result['info'].get('persona_ids', []))}")
                print(f"     granularity: {result['info'].get('granularity')}")
                print(f"     covered objectives: {result['info'].get('covered_objectives', [])}")
        return 0 if result["ok"] else 1
    if cmd == "extract-tasks":
        return cmd_extract_tasks(argv[2:])
    if cmd == "extract-fields":
        return cmd_extract_fields(argv[2:])
    if cmd == "extract-routes":
        return cmd_extract_routes(argv[2:])
    if cmd == "extract-roles":
        return cmd_extract_roles(argv[2:])
    if cmd == "extract-openapi":
        return cmd_extract_openapi(argv[2:])

    if cmd == "scan-artifacts":
        if len(argv) != 3:
            print("usage: manual_helper.py scan-artifacts <project-root>", file=sys.stderr)
            return 2
        entries = scan_artifacts(Path(argv[2]))
        json.dump(entries, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    # Internal subcommand used by tests (P6). Not documented in SKILL.md
    # because callers should use `init-skill`, which calls this internally.
    if cmd == "_detect_layout":
        if len(argv) != 3:
            print("usage: manual_helper.py _detect_layout <project-root>", file=sys.stderr)
            return 2
        result = _detect_project_layout(Path(argv[2]))
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if cmd == "parse-citations":
        if len(argv) != 3:
            print("usage: manual_helper.py parse-citations <md-path>", file=sys.stderr)
            return 2
        result = parse_citations(Path(argv[2]))
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if cmd == "fill-citation-shas":
        return _cmd_fill_citation_shas(argv[2:])

    if cmd == "diff-artifacts":
        if len(argv) != 4:
            print("usage: manual_helper.py diff-artifacts <project-root> <md-path>", file=sys.stderr)
            return 2
        proj_root = Path(argv[2])
        md_path = Path(argv[3])
        # P7: fail loud when inputs are missing.
        # md-path is required for the idempotency ledger; if it doesn't
        # exist the LLM almost certainly got the path wrong — surface that.
        if not md_path.exists():
            print(
                f"error: manual.md not found at {md_path}. "
                f"Run `manual_helper.py init {md_path}` first, or pass "
                f"the path of an existing manual to diff against.",
                file=sys.stderr,
            )
            return 2
        # project-root is required too; if the path doesn't exist OR it
        # has no `docs/superpowers/` tree, warn (don't hard-fail) so the
        # caller can still proceed with llm_only_mode.
        if not proj_root.exists():
            print(
                f"error: project_root does not exist: {proj_root}",
                file=sys.stderr,
            )
            return 2
        if not (proj_root / "docs" / "superpowers").exists():
            print(
                f"warning: {proj_root}/docs/superpowers/ not found. "
                f"Run with `manual_helper.py scan-artifacts {proj_root}` "
                f"to confirm, or set `llm_only_mode: true` in "
                f"manual-config.json to skip the artifact scan.",
                file=sys.stderr,
            )
        result = diff_artifacts(proj_root, md_path)
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if cmd == "html-template-version":
        print(html_template_version())
        return 0

    if cmd == "html-on-disk-version":
        if len(argv) != 3:
            print(
                "usage: manual_helper.py html-on-disk-version <html-path>",
                file=sys.stderr,
            )
            return 2
        try:
            print(html_on_disk_version(Path(argv[2])))
        except FileNotFoundError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        return 0

    if cmd == "regenerate-html-if-stale":
        if len(argv) != 3:
            print(
                "usage: manual_helper.py regenerate-html-if-stale <html-path>",
                file=sys.stderr,
            )
            return 2
        result = regenerate_html_if_stale(Path(argv[2]))
        print(f"{result}: {argv[2]}")
        return 0

    if cmd == "write-index":
        if len(argv) < 4:
            print(
                "usage: manual_helper.py write-index <html-dir> <md-path> [more...]",
                file=sys.stderr,
            )
            return 2
        html_dir = Path(argv[2])
        md_paths = [Path(p) for p in argv[3:]]
        out = write_index(html_dir, md_paths)
        print(f"wrote: {out}")
        return 0

    if cmd == "build-standalone":
        if len(argv) < 5:
            print(
                "usage: manual_helper.py build-standalone <html-template> <html-out> <md-path> [more...]",
                file=sys.stderr,
            )
            return 2
        tmpl = Path(argv[2])
        out = Path(argv[3])
        md_paths = [Path(p) for p in argv[4:]]
        result = build_standalone(tmpl, out, md_paths)
        print(f"wrote: {result}")
        return 0

    if cmd == "auto-promote-annotated":
        # v1.1.0: walk one or more .md files and switch every
        # `![alt](path.png)` reference to its `.annotated.png` sibling
        # if that sibling exists on disk. Used by the post-recording
        # pass and by the new `screenshot_uses_annotated` validator
        # check to fix manuals whose alt text describes a red box but
        # whose image is the bare unannotated PNG.
        #
        # Usage: manual_helper.py auto-promote-annotated <md-path> [more...]
        # Prints a one-line summary per file and a final tally.
        # Use --dry-run to print without writing.
        if len(argv) < 3:
            print(
                "usage: manual_helper.py auto-promote-annotated [--dry-run] <md-path> [more...]",
                file=sys.stderr,
            )
            return 2
        dry_run = "--dry-run" in argv
        paths = [Path(a) for a in argv[2:] if not a.startswith("--")]
        if not paths:
            print("error: no <md-path> provided", file=sys.stderr)
            return 2
        total_promoted = 0
        for md_path in paths:
            if not md_path.exists():
                print(f"warn: {md_path} does not exist, skipping", file=sys.stderr)
                continue
            md_text = md_path.read_text(encoding="utf-8")
            new_text, n, promoted = auto_promote_annotated_paths(
                md_text, md_dir=md_path.parent, prefer_annotated=True,
            )
            action = "would promote" if dry_run else "promoted"
            if n == 0:
                print(f"{md_path}: 0 references needed {action}")
            else:
                print(f"{md_path}: {action} {n} reference(s)")
                for p_old in promoted[:10]:
                    print(f"  - {p_old}")
                if len(promoted) > 10:
                    print(f"  ... and {len(promoted) - 10} more")
            if not dry_run and n > 0:
                md_path.write_text(new_text, encoding="utf-8")
            total_promoted += n
        print(f"TOTAL: {total_promoted} reference(s) {'would be ' if dry_run else ''}promoted across {len(paths)} file(s)")
        return 0

    if cmd == "write-recording-manifest":
        # v1.1.0 (hard gate): write docs/user-manual/recording_manifest.json
        # so validate-output.py can verify the recording phase actually ran.
        # The recorder skill CLI's stdout is the source of truth for
        # `screenshots_written` / `videos_written`; the LLM agent loops
        # over them and passes the paths here. The manifest is what the
        # v1.1.0 validator hard-gate reads. Without this file the manual
        # is treated as a draft and validate-output exits 2.
        #
        # Usage: manual_helper.py write-recording-manifest <md-path>
        #        --dev-url URL [--session-id SID] [--recorder-exit N]
        #        [--screenshot <path>]... [--video <path>]...
        # Examples:
        #   manual_helper.py write-recording-manifest \
        #       docs/user-manual/manual/sys.md \
        #       --dev-url http://localhost:8080 \
        #       --session-id 2026-06-27T12:00:00Z \
        #       --recorder-exit 0 \
        #       --screenshot screenshots/sys/01-list.png \
        #       --video screenshots/sys/demo.mp4
        if len(argv) < 3:
            print(
                "usage: manual_helper.py write-recording-manifest <md-path> "
                "--dev-url URL [--session-id SID] [--recorder-exit N] "
                "[--screenshot PATH]... [--video PATH]...",
                file=sys.stderr,
            )
            return 2
        md_path = Path(argv[2])
        dev_url = ""
        session_id = ""
        recorder_exit = 0
        shots: list[Path] = []
        vids: list[Path] = []
        i = 3
        while i < len(argv):
            a = argv[i]
            if a == "--dev-url" and i + 1 < len(argv):
                dev_url = argv[i + 1]
                i += 2
                continue
            if a == "--session-id" and i + 1 < len(argv):
                session_id = argv[i + 1]
                i += 2
                continue
            if a == "--recorder-exit" and i + 1 < len(argv):
                try:
                    recorder_exit = int(argv[i + 1])
                except ValueError:
                    print(f"error: --recorder-exit value {argv[i + 1]!r} is not an int", file=sys.stderr)
                    return 2
                i += 2
                continue
            if a == "--screenshot" and i + 1 < len(argv):
                shots.append(Path(argv[i + 1]))
                i += 2
                continue
            if a == "--video" and i + 1 < len(argv):
                vids.append(Path(argv[i + 1]))
                i += 2
                continue
            if a.startswith("--"):
                print(f"warn: unknown flag {a!r} ignored", file=sys.stderr)
                i += 1
                continue
            i += 1
        if not md_path.exists():
            print(f"error: {md_path} does not exist", file=sys.stderr)
            return 2
        if not dev_url:
            print("error: --dev-url is required", file=sys.stderr)
            return 2
        # Probe readiness at this moment; the manifest records it so the
        # validator can tell "recorder ran while dev server was reachable"
        # from "recorder ran against a dead dev server (worthless assets)".
        try:
            md_for_readiness = md_path.resolve().parent.parent.parent  # docs/user-manual/manual/x.md -> <proj>
            readiness = check_recording_readiness(md_for_readiness)
        except Exception as e:  # noqa: BLE001 - any error is informational
            readiness = {"status": "n/a", "summary": f"probe failed: {type(e).__name__}: {e}"}
        out = write_recording_manifest(
            md_path,
            dev_server_url=dev_url,
            screenshots_written=shots,
            videos_written=vids,
            recorder_cli_exit=recorder_exit,
            recording_readiness_at_run=readiness,
            recorder_session_id=session_id,
        )
        # Read it back and print a one-line summary.
        from .common import now_et
        print(f"wrote: {out}")
        print(f"  dev_url: {dev_url}")
        print(f"  recorder_exit: {recorder_exit}  readiness: {readiness.get('status', 'n/a')}")
        print(f"  screenshots: {len(shots)}  videos: {len(vids)}  ({now_et()})")
        return 0

    if cmd == "read-config":
        cmd_read_config(argv[2:])
        return 0
    if cmd == "init-db":
        rc = cmd_init_db(argv[2:])
        return rc if rc is not None else 0
    if cmd == "upsert-manual":
        rc = cmd_upsert_manual(argv[2:])
        return rc if rc is not None else 0
    if cmd == "upload-asset":
        rc = cmd_upload_asset(argv[2:])
        return rc if rc is not None else 0

    if cmd == "prune-silent-backups":
        # v1.2.0: delete recorder `.silent.mp4` backups whose narrated
        # sibling is referenced by a manual. Default = dry-run (report
        # only); pass --apply to actually unlink. Pass --manual <path>
        # one+ times to scope which manuals drive "in use" (default:
        # # auto-discover <screenshots-dir>/../manual/*.md).
        positionals = [a for a in argv[2:] if not a.startswith("--")]
        apply_flag = "--apply" in argv
        manual_args: list[str] = []
        i = 2
        while i < len(argv):
            if argv[i] == "--manual" and i + 1 < len(argv):
                manual_args.append(argv[i + 1])
                i += 2
                continue
            i += 1
        if not positionals:
            print(
                "usage: manual_helper.py prune-silent-backups <screenshots-dir> "
                "[--manual <md-path>...] [--apply]",
                file=sys.stderr,
            )
            return 2
        shots = Path(positionals[0])
        if not manual_args:
            auto_dir = shots.parent / "manual"
            manual_args = sorted(str(p) for p in auto_dir.glob("*.md")) if auto_dir.is_dir() else []
        report = prune_silent_backups(shots, [Path(m) for m in manual_args], apply=apply_flag)
        import json as _json
        print(_json.dumps(report, ensure_ascii=False, indent=2))
        if not apply_flag and report["prunable"]:
            print(
                f"\n(dry-run) {len(report['prunable'])} prunable, "
                f"{len(report['keep_orphan'])} kept. Re-run with --apply to delete.",
                file=sys.stderr,
            )
        elif apply_flag:
            print(
                f"\n(deleted {len(report['deleted'])} files, "
                f"{report['bytes_freed']} bytes)",
                file=sys.stderr,
            )
        return 0

    print(f"unknown subcommand: {cmd}", file=sys.stderr)
    print(__doc__, file=sys.stderr)
    return 2



