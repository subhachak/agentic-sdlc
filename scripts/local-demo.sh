#!/usr/bin/env bash
# Local dry-run of the agentic QA pipeline — no GitHub calls, prints what
# would have been posted instead. Requires ANTHROPIC_API_KEY to be set.
set -euo pipefail

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "Set ANTHROPIC_API_KEY first." >&2
  exit 1
fi

cd "$(dirname "$0")/.."

echo "== Installing sample app deps =="
(cd sample-app && npm install && npx playwright install --with-deps chromium)

echo "== Installing orchestrator deps =="
pip install -r orchestrator/requirements.txt --break-system-packages -q

BASE_SHA=$(git rev-list --max-parents=0 HEAD)
HEAD_SHA=$(git rev-parse HEAD)

echo "== Running pipeline: ${BASE_SHA:0:7}..${HEAD_SHA:0:7} =="
export DRY_RUN=1
python -m orchestrator.run \
  --repo demo/claims-lite \
  --pr-number 1 \
  --base-sha "$BASE_SHA" \
  --head-sha "$HEAD_SHA"
