"""Every filesystem location the QA pipeline touches, resolved in one place.

Nodes used to each recompute `Path(__file__).parents[2]`, which silently
encoded how deep in the tree they happened to sit. Moving the pipeline broke
all of them at once. Anything that needs a path imports it from here.
"""
from __future__ import annotations

from pathlib import Path

# .../execution-plane/qa/orchestrator/paths.py -> .../execution-plane/qa
QA_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = QA_ROOT.parents[1]

# The application under test. Playwright specs must live inside it: Node
# resolves imports by walking up from the spec file, so a spec anywhere else
# cannot see demo-app/node_modules.
APP_ROOT = REPO_ROOT / "demo-app"

LIBRARY_DIR = QA_ROOT / "test-scripts"
FEATURES_FILE = QA_ROOT / "features.yaml"

GENERATED_DIR = APP_ROOT / "generated-tests"
DATA_STORE = APP_ROOT / "lib" / "data-store.json"

EVIDENCE_DIR = REPO_ROOT / "evidence"
RESULTS_FILE = EVIDENCE_DIR / "results.json"

# git pathspecs for the diff that triggers a QA run, relative to REPO_ROOT
DIFF_PATHS = ["demo-app/", "execution-plane/qa/features.yaml"]
