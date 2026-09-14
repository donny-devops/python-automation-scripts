#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for python-automation-scripts.
# Installs the project editable, system-wide, so the console commands
# (web-scraper, to-dojo, desktop-assistant) and dev tools (ruff, pytest)
# are on PATH in every shell without activating a virtualenv.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# The base image ships an externally-managed CPython (PEP 668), so a plain
# `pip install` is refused. Install into the system interpreter with
# --break-system-packages (sudo is passwordless in the Cloud Agent VM) so the
# generated console scripts land in /usr/local/bin, which is already on PATH.
PIP=(sudo python3 -m pip install --break-system-packages)

# dev  -> ruff, pytest, and the scraper/dojo runtime libraries used by tests
# scraper -> full web-scraper stack (pandas/openpyxl/playwright client, etc.)
# dojo -> To-Dojo runtime deps
# The desktop assistant extra is intentionally omitted: it is host-only
# (microphone/TTS/clipboard) and is not exercised in a headless VM.
"${PIP[@]}" -e ".[dev,scraper,dojo]"

echo "python-automation-scripts install complete."
