#!/usr/bin/env bash
set -euo pipefail

# Launchd entry point: loads .env (launchd has no EnvironmentFile) and starts the server.
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$project_dir"

if [[ -f .env ]]; then
    set -a
    source .env
    set +a
fi

export PYTHONPATH="$project_dir/src"
exec "$project_dir/.venv/bin/python" src/octo_satellite/main.py
