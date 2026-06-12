"""CLI entry for the recorder. No argparse — matches user-manual's manual_helper.py style."""
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path


def _usage() -> None:
    print("recorder CLI - opt-in plugin for the user-manual skill")
    print()
    print("Usage:")
    print("  python3 -m recorder_plugin.cli run <script.json>")
    print("  python3 -m recorder_plugin.cli apply-ai-responses <output-dir>")
    print("  python3 -m recorder_plugin.cli --version")
    print("  python3 -m recorder_plugin.cli --help")


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("--help", "-h", "help"):
        _usage()
        return 0
    if argv[1] in ("--version", "-V"):
        from recorder_plugin import __version__
        print(__version__)
        return 0
    if argv[1] == "run":
        if len(argv) != 3:
            print("usage: python3 -m recorder_plugin.cli run <script.json>", file=sys.stderr)
            return 2
        from recorder_plugin.script import run_script
        result = asyncio.run(run_script(Path(argv[2])))
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "ok" else 1
    if argv[1] == "apply-ai-responses":
        if len(argv) != 3:
            print("usage: python3 -m recorder_plugin.cli apply-ai-responses <output-dir>", file=sys.stderr)
            return 2
        from recorder_plugin.vision import list_pending, response_path_for, apply_response
        out_dir = Path(argv[2])
        pending = list_pending(out_dir)
        if not pending:
            print(f"NO_PENDING: {out_dir}")
            return 0
        results = []
        for req in pending:
            resp = response_path_for(req)
            r = apply_response(req, resp, out_dir)
            results.append(r)
        print(json.dumps({"applied": [r for r in results if r["status"] == "applied"],
                         "skipped": [r for r in results if r["status"] == "skipped"]},
                        indent=2, default=str))
        return 0 if all(r["status"] == "applied" for r in results) else 1
    print(f"unknown subcommand: {argv[1]}", file=sys.stderr)
    _usage()
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
