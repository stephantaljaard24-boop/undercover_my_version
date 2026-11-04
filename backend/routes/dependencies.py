"""What a route asks FastAPI for."""

import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends

from backend.db import connect


def get_db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


Db = Annotated[sqlite3.Connection, Depends(get_db)]
