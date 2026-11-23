from collections.abc import Callable, Iterator
from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import Connection

from agent.harness import agents
from agent.harness.checkpoints import Checkpoints
from agent.tests.stubs import backend_over
from agent.undercover.backend import Backend
from agent.undercover.claim_agent import ClaimAgent
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


@pytest.fixture
def saver() -> BaseCheckpointSaver:
    """Where the graphs save their progress. It outlives a graph, as a database does."""
    return InMemorySaver()


@pytest.fixture
def checkpoints(saver: BaseCheckpointSaver) -> Checkpoints:
    return lambda: nullcontext(saver)


@pytest.fixture
def make_claims(
    backend: Backend, checkpoints: Checkpoints
) -> Callable[[BaseChatModel | None], ClaimAgent]:
    """Build a claim agent on the model, which stands in for a restart."""
    return lambda llm=None: ClaimAgent(backend, checkpoints, llm)
