"""Validates the demo environment before going live: config loads, DB schema
is present, and the configured LLM provider is reachable.

Usage: uv run python scripts/preflight_check.py
Exits non-zero on any failure.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import ValidationError  # noqa: E402
from sqlalchemy import inspect  # noqa: E402

from app.core.config import Settings, get_settings  # noqa: E402
from app.core.db import get_engine, init_db  # noqa: E402

EXPECTED_TABLES = {"runs", "audit_log"}


async def check_config() -> tuple[bool, str]:
    try:
        Settings()
        return True, "config loads"
    except ValidationError as exc:
        return False, f"config invalid: {exc}"


async def check_db_schema() -> tuple[bool, str]:
    try:
        await init_db()
        engine = get_engine()
        async with engine.connect() as conn:
            tables = set(await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names()))
        missing = EXPECTED_TABLES - tables
        if missing:
            return False, f"missing tables: {sorted(missing)}"
        return True, f"DB schema present: {sorted(tables)}"
    except Exception as exc:  # noqa: BLE001 - report any DB failure as a preflight failure
        return False, f"DB check failed: {exc}"


async def check_llm_provider(settings: Settings) -> tuple[bool, str]:
    if settings.llm_provider_adapter == "mock":
        return True, "mock adapter — no network required"

    if not settings.anthropic_api_key:
        return False, "claude adapter configured but ANTHROPIC_API_KEY is not set"

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        await client.with_options(timeout=10.0).messages.create(
            model=settings.claude_model,
            max_tokens=8,
            messages=[{"role": "user", "content": "ping"}],
        )
        return True, f"claude adapter reachable (model={settings.claude_model})"
    except anthropic.AuthenticationError:
        return False, "claude adapter: invalid API key"
    except Exception as exc:  # noqa: BLE001 - report any reachability failure as a preflight failure
        return False, f"claude adapter unreachable: {exc}"


async def main() -> int:
    settings = get_settings()
    checks = [
        await check_config(),
        await check_db_schema(),
        await check_llm_provider(settings),
    ]

    ok = True
    for passed, message in checks:
        symbol = "PASS" if passed else "FAIL"
        print(f"[{symbol}] {message}")
        ok = ok and passed

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
