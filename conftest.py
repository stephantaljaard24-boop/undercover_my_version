import pytest
from fastapi.testclient import TestClient

from backend import agent_client
from backend.main import app
from backend.seed import seed


@pytest.fixture(autouse=True)
def sqlite_only(monkeypatch):
    """No test reaches Supabase, whatever the shell has."""
    monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.fixture(autouse=True)
def notified(monkeypatch) -> list[str]:
    """The claims the backend told the agent about. No test reaches a real service."""
    claims: list[str] = []
    monkeypatch.setattr(agent_client, "notify_signed_off", claims.append)
    return claims


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "test.db"))
    seed()
    return TestClient(app)
