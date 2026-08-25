#!/usr/bin/env python
"""Apply promotion candidates into the script library.

Run separately from the pipeline, on purpose. The job that executes
agent-written specs holds no write token, so it proposes candidates and this
applies them under whatever review the client already runs. Nothing here
executes a spec — it copies a file that has already been validated and has
already passed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from orchestrator.paths import LIBRARY_DIR, MANIFEST_FILE  # noqa: E402
from orchestrator.promotion import manifest_entry, verify  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates", type=Path,
                        help="promotions.json from a run — written into the evidence "
                             "directory, which is what CI uploads")
    parser.add_argument("--only", action="append", default=[],
                        help="script id to promote; repeatable. Default: those "
                             "that close a coverage gap")
    parser.add_argument("--all", action="store_true",
                        help="promote every passing candidate, not only gap-closers")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    payload = json.loads(args.candidates.read_text())
    candidates = payload if isinstance(payload, list) else payload.get("promotion_candidates", [])

    chosen = [
        c for c in candidates
        if (c["script_id"] in args.only)
        or (not args.only and (args.all or c["closes_coverage_gap"]))
    ]
    if not chosen:
        print("nothing to promote")
        return 0

    manifest = json.loads(MANIFEST_FILE.read_text())
    known = {e["id"] for e in manifest["scripts"]}

    for candidate in chosen:
        if candidate["script_id"] in known:
            print(f"skip {candidate['script_id']}: already in the library", file=sys.stderr)
            continue

        # Verified from the candidate's own source, not from a path. The job
        # that produced it was a CI runner that no longer exists, and only the
        # state file and the evidence directory survive it — a path into
        # `generated-tests` is dead by the time anyone reads this.
        problem = verify(candidate)
        if problem:
            print(f"refuse {candidate['script_id']}: {problem}", file=sys.stderr)
            continue

        entry = manifest_entry(candidate)
        target = LIBRARY_DIR / entry["file"]
        provenance = candidate.get("provenance") or {}
        print(f"promote {candidate['script_id']}")
        print(f"   covers (observed): {', '.join(candidate['covers_modules'])}")
        print(f"   from run:          {provenance.get('run', '?')}"
              f" at {(provenance.get('head_sha') or '?')[:7]}")
        print(f"   sha256:            {candidate['sha256'][:16]}…")
        if candidate.get("intercepted"):
            print(f"   NOTE: intercepted {', '.join(candidate['intercepted'])} — those "
                  f"requests never reached the server and earn no coverage")
        if candidate["new_modules"]:
            print(f"   closes gap on:     {', '.join(candidate['new_modules'])}")
        if args.dry_run:
            continue

        target.write_text(candidate["source"])
        manifest["scripts"].append(entry)
        known.add(entry["id"])

    if not args.dry_run:
        MANIFEST_FILE.write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"\nupdated {MANIFEST_FILE}")
        print("Review the promoted specs before committing — a script in the library "
              "is run against every change that reaches its modules.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
