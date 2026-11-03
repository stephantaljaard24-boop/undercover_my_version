import pytest
from fastapi.testclient import TestClient

from agent import main, tools
from backend.main import app


@pytest.fixture(autouse=True)
def backend_in_process(client, monkeypatch):
    monkeypatch.setattr(tools, "backend", lambda: TestClient(app))
    monkeypatch.setattr(main, "RETRY_DELAY", 0)
    return client
