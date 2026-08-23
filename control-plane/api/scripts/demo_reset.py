"""Restore the demo to a clean seed state: wipes the SQLite DB, the LangGraph
checkpoint DB, and the local test_cases.json file, then recreates schema.

Usage: uv run python scripts/demo_reset.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings  # noqa: E402
from app.core.db import init_db  # noqa: E402


def _delete_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()
        print(f"deleted {path}")


def main() -> None:
    settings = get_settings()
    root = Path(__file__).resolve().parent.parent

    _delete_if_exists(root / settings.db_file_path)
    _delete_if_exists(root / settings.checkpointer_db_path)
    _delete_if_exists(root / "data" / "test_cases.json")

    asyncio.run(init_db())
    print("schema recreated — demo is at clean seed state")


if __name__ == "__main__":
    main()
