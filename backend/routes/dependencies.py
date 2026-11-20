"""What a route asks FastAPI for."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy import Connection

from backend.db import connection

Db = Annotated[Connection, Depends(connection)]
