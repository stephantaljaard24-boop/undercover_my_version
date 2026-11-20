"""The database: Supabase when DATABASE_URL is set, else SQLite."""

import os
from collections.abc import Iterator
from functools import cache
from pathlib import Path

from sqlalchemy import Connection, Engine, create_engine, inspect, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool

from backend.schema import metadata

DEFAULT_DB = Path(__file__).parent / "undercover.db"
SCHEMA = "undercover"
POOL_SIZE = 2
POOL_OVERFLOW = 2


def db_path() -> Path:
    """Return the SQLite file, from UNDERCOVER_DB if it is set."""
    return Path(os.getenv("UNDERCOVER_DB") or DEFAULT_DB)


def postgres_url(url: str) -> URL:
    """Turn a Postgres connection string into one for the psycopg driver."""
    return make_url(url).set(drivername="postgresql+psycopg")


@cache
def make_engine(url: URL) -> Engine:
    """Build the engine for a URL, once. Postgres keeps at most 4 connections."""
    if url.drivername == "sqlite":
        return create_engine(url, poolclass=NullPool)
    return create_engine(
        url,
        connect_args={"options": f"-c search_path={SCHEMA}"},
        pool_size=POOL_SIZE,
        max_overflow=POOL_OVERFLOW,
        pool_pre_ping=True,
    )


def engine() -> Engine:
    """Return the engine for Supabase if DATABASE_URL is set, else for SQLite."""
    if url := os.getenv("DATABASE_URL"):
        return make_engine(postgres_url(url))
    return make_engine(URL.create("sqlite", database=str(db_path())))


def connection() -> Iterator[Connection]:
    """Open a connection for the length of one request."""
    with engine().connect() as conn:
        yield conn


def describe() -> str:
    """Say which database the engine is on, without the password."""
    return engine().url.render_as_string(hide_password=True)


def tables_exist() -> bool:
    """True when the database already has the claims table."""
    return inspect(engine()).has_table("claims")


def reset_schema() -> None:
    """Empty the database and create the tables again.

    On Postgres that drops the whole undercover schema, the agent's saved progress
    included. The agent creates its own tables again the next time it runs.
    """
    if engine().dialect.name == "postgresql":
        with engine().begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
            conn.execute(text(f"CREATE SCHEMA {SCHEMA}"))
    else:
        metadata.drop_all(engine())
    metadata.create_all(engine())
