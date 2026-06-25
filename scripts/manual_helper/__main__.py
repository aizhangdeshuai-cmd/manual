"""Allow `python3 -m manual_helper <subcmd>` to work after the package split.

All dispatch is in `cli.main`; this file just calls it.

Subcommands (full list in SKILL.md section 7):
  now-et, init, init-skill, validate-config, check-recording-readiness,
  extract-tasks/fields/routes/roles/openapi, scan-artifacts,
  parse-citations, fill-citation-shas, diff-artifacts,
  html-template-version, html-on-disk-version, regenerate-html-if-stale,
  write-index, build-standalone,
  read-config, init-db, upsert-manual, upload-asset,
  # recorder subcommands (tts-synth, concat-narration, mux-audio, run,
  # apply-ai-responses) live in the recorder skill at
  # ~/.agents/skills/recorder; see SKILL.md §13.
"""
from __future__ import annotations

# When this file is run as `python3 -m manual_helper`, Python sets
# __package__ to "manual_helper" automatically. We use absolute imports
# of cli here because relative imports (.cli) don't work in __main__
# when the module is run directly.
import manual_helper.cli as _cli
import sys

if __name__ == "__main__":
    sys.exit(_cli.main(sys.argv))
