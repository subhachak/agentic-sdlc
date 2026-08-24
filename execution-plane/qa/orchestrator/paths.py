"""Every filesystem location the QA pipeline touches, resolved in one place.

Nodes used to each recompute `Path(__file__).parents[2]`, which silently
encoded how deep in the tree they happened to sit. Moving the pipeline broke
all of them at once. Anything that needs a path imports it from here.
"""
from __future__ import annotations

import os
from pathlib import Path

# .../execution-plane/qa/orchestrator/paths.py -> .../execution-plane/qa
QA_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = QA_ROOT.parents[1]

# The application under test. Playwright specs must live inside it: Node
# resolves imports by walking up from the spec file, so a spec anywhere else
# cannot see demo-app/node_modules.
# QA_APP_ROOT lets a caller point the run at a checkout of the branch under
# test instead of the working copy. Without it the pipeline diffs the change
# and then tests whatever happens to be on disk — which is the old code.
APP_ROOT = Path(os.environ.get("QA_APP_ROOT") or (REPO_ROOT / "demo-app"))

LIBRARY_DIR = QA_ROOT / "test-scripts"
FEATURES_FILE = QA_ROOT / "features.yaml"
# Seeded code-intelligence graph. Derived from the repository in production.
CODE_GRAPH_FILE = QA_ROOT / "code-graph.json"

GENERATED_DIR = APP_ROOT / "generated-tests"
DATA_STORE = APP_ROOT / "lib" / "data-store.json"

# Evidence belongs to the checkout that produced it. Deriving this from the
# repository root instead meant a run against a branch wrote its results
# beside that checkout while the gate read a stale file next to the working
# copy — and reported that fewer tests had run than were assigned.
# The root of whatever checkout is under test — the working copy normally,
# a worktree of the branch when a run is testing a proposed change.
CHECKOUT_ROOT = APP_ROOT.parent
EVIDENCE_DIR = CHECKOUT_ROOT / "evidence"
RESULTS_FILE = EVIDENCE_DIR / "results.json"

# git pathspecs for the diff that triggers a QA run, relative to REPO_ROOT
DIFF_PATHS = ["demo-app/", "execution-plane/qa/features.yaml"]
