#!/usr/bin/env bash
# Local dry-run of the agentic QA pipeline — no GitHub calls, prints what
# would have been posted instead. Requires ANTHROPIC_API_KEY to be set; the
# repository-root .env is loaded automatically.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"
QA_DIR="$ROOT/execution-plane/qa"
QA_VENV="$QA_DIR/.venv"

if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "Set ANTHROPIC_API_KEY first, or run ./run.sh keys import." >&2
  exit 1
fi

echo "== Installing the app under test =="
(cd demo-app && npm install --silent && npx playwright install --with-deps chromium)

# Playwright's webServer runs `npm run start`, which is `next start` and needs a
# production build to exist. Without this the run dies before any test executes.
echo "== Building the app under test =="
(cd demo-app && npm run build)

# The pipeline gets its own environment rather than installing into whatever
# `python` happens to be. On a machine where `python` is not on PATH at all —
# which is most of them now — the previous approach failed on its first line.
echo "== Preparing the pipeline environment =="
if [ ! -x "$QA_VENV/bin/python" ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv "$QA_VENV" >/dev/null
  else
    python3 -m venv "$QA_VENV"
  fi
fi
if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$QA_VENV/bin/python" -q \
    -r "$QA_DIR/orchestrator/requirements-dev.txt"
else
  "$QA_VENV/bin/python" -m pip install -q \
    -r "$QA_DIR/orchestrator/requirements-dev.txt"
fi

BASE_SHA=$(git rev-list --max-parents=0 HEAD)
HEAD_SHA=$(git rev-parse HEAD)

echo "== Running pipeline: ${BASE_SHA:0:7}..${HEAD_SHA:0:7} =="
export DRY_RUN=1
cd "$QA_DIR"
"$QA_VENV/bin/python" -m orchestrator.run \
  --repo demo/claims-lite \
  --pr-number 1 \
  --base-sha "$BASE_SHA" \
  --head-sha "$HEAD_SHA"
