#!/usr/bin/env bash
# Convenience wrapper: run a recorder script from the repo root.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/../.."
exec python3 -m recorder_plugin.cli run "$@"
