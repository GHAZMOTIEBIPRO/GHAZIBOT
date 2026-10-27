#!/usr/bin/env bash
# Local test environment that matches CI: its own virtualenv with the pinned
# dev requirements, so a globally installed pytest or ruff (e.g. a uv tool with
# its own interpreter and no pandas) is never the one that runs.
#
#   bash scripts/dev_setup.sh          # once
#   .venv/bin/python -m pytest -q      # tests with the project's dependencies
#   .venv/bin/ruff check .             # the CI ruff version
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip >/dev/null
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest --version
.venv/bin/ruff --version
