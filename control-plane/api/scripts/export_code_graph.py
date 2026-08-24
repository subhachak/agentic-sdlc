#!/usr/bin/env python
"""Write the derived graph to where the execution plane reads it.

Run after seeding. The file it produces replaces one that used to be
hand-authored, so the two planes now disagree only if this is stale — which
the provenance stamp makes visible rather than silent.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.adapters.registry import build_entity_resolver  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.context_graph import SqlContextGraph  # noqa: E402
from app.core.db import init_db  # noqa: E402
from app.core.graph_export import build_export  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parents[3] / "execution-plane/qa/code-graph.json"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", default="demo-app", help="repository subtree to export")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--stdout", action="store_true", help="print instead of writing")
    args = parser.parse_args()

    await init_db()
    graph = SqlContextGraph(build_entity_resolver(get_settings()))
    export = await build_export(graph, scope=args.scope)

    if not export["modules"]:
        print(
            f"refusing to write an empty export for scope {args.scope!r} — "
            f"seed the graph first (scripts/seed_graph.py)",
            file=sys.stderr,
        )
        return 1

    payload = json.dumps(export, indent=2) + "\n"
    if args.stdout:
        print(payload)
        return 0

    args.out.write_text(payload)
    provenance = export["provenance"]
    print(f"wrote {args.out}")
    print(f"  scope       {args.scope}")
    print(f"  commit      {provenance.get('commit_sha') or 'UNPINNED'}")
    print(f"  modules     {len(export['modules'])}")
    print(f"  depends_on  {len(export['depends_on'])}")
    print(f"  files       {len(export['file_dependents'])} with at least one dependent")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
