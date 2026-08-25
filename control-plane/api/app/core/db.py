from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.models.base import Base

# Import models so they register on Base.metadata before create_all() runs.
from app.models import (  # noqa: F401
    audit_log,
    dispatch,
    graph,
    project,
    run,
    setting,
)


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url)


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def init_db() -> None:
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _add_missing_columns(conn)


# create_all builds tables it has never seen; it does not alter ones it has.
# There is no migration tool here, so a column added to an existing model
# needs this or an existing database silently keeps answering without it.
_ADDED_COLUMNS = (
    ("runs", "project", "VARCHAR DEFAULT 'default'"),
)


async def _add_missing_columns(conn) -> None:
    from sqlalchemy import text

    for table, column, definition in _ADDED_COLUMNS:
        existing = {
            row[1]
            for row in (await conn.exec_driver_sql(f"PRAGMA table_info({table})")).fetchall()
        }
        if existing and column not in existing:
            await conn.exec_driver_sql(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session
