from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection

from agent.harness import agents
from agent.tests.stubs import backend_over
from agent.undercover.backend import Backend
from backend.db import engine


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(agents, "RETRY_DELAY", 0)


@pytest.fixture
def backend(client: TestClient) -> Backend:
    """The agent's way to the backend, over the in-process app and a fresh database."""
    return backend_over(client)


@pytest.fixture
def db(client: TestClient) -> Iterator[Connection]:
    """The same database, to check what the backend stored."""
    with engine().connect() as conn:
        yield conn
