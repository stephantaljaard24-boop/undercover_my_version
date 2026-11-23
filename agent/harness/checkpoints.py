"""Saving a graph's progress in Postgres, so it survives a restart."""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import Connection, sql
from psycopg.rows import DictRow, dict_row

Checkpoints = Callable[[], AbstractContextManager[BaseCheckpointSaver]]


@contextmanager
def postgres_checkpoints(url: str, schema: str) -> Iterator[PostgresSaver]:
    """Open a saver on a schema, make its tables if they are missing, and close it.

    The connection lives only as long as the work, because the session pooler
    drops idle connections.
    """
    with Connection[DictRow].connect(
        url,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
        options=f"-c search_path={schema}",
    ) as connection:
        make_schema = sql.SQL("CREATE SCHEMA IF NOT EXISTS {}")
        connection.execute(make_schema.format(sql.Identifier(schema)))
        saver = PostgresSaver(connection)
        saver.setup()
        yield saver
