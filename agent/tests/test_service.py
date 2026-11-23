from contextlib import nullcontext

import pytest
from fastapi.testclient import TestClient

from agent import service
from agent.tests.stubs import Killed, approval, call, script, sign_off
from agent.undercover.claim_agent import ClaimAgent
from backend import store


@pytest.fixture
def service_client(monkeypatch, backend, checkpoints) -> TestClient:
    """The agent's service over the test backend, and a model nobody calls."""
    claims = ClaimAgent(backend, checkpoints, script())
    monkeypatch.setattr(service, "open_claims", lambda: nullcontext(claims))
    return TestClient(service.app)


def hold(make_claims, claim_id="CLM-1003"):
    """Work a claim that is over the limit, so it waits for a handler."""
    make_claims(script(*approval(claim_id, payout="1500.00"))).work_claim(claim_id)


def resume(service_client, claim_id="CLM-1003"):
    path = service.app.url_path_for("resume_claim", claim_id=claim_id)
    return service_client.post(path)


def test_a_signed_off_claim_is_paid_once(service_client, backend, make_claims):
    hold(make_claims)
    sign_off("CLM-1003")
    response = resume(service_client)
    assert response.status_code == 202
    assert response.json() == {"claim_id": "CLM-1003"}
    claim = backend.claim("CLM-1003")
    assert claim.status == "decided"
    assert claim.payment is not None
    assert claim.payment.amount == "1500.00"
    assert resume(service_client).status_code == 202
    assert backend.claim("CLM-1003") == claim


def test_a_claim_still_waiting_for_a_sign_off_is_left_alone(
    service_client, backend, make_claims
):
    hold(make_claims)
    assert resume(service_client).status_code == 202
    claim = backend.claim("CLM-1003")
    assert claim.status == "awaiting_sign_off"
    assert claim.payment is None


def test_a_claim_the_command_line_is_working_is_left_alone(
    service_client, backend, db, make_claims
):
    with pytest.raises(Killed):
        make_claims(
            script(call("get_claim", claim_id="CLM-1001"), Killed())
        ).work_claim("CLM-1001")
    assert resume(service_client, "CLM-1001").status_code == 202
    assert backend.claim("CLM-1001").status == "in_progress"
    assert store.claim_row(db, "CLM-1001")["attempts"] == 0


def test_the_service_has_a_health_check_and_follows_the_api_rules(service_client):
    assert service_client.get("/api/health").json() == {"status": "ok"}
    for path, methods in service.app.openapi()["paths"].items():
        for method, operation in methods.items():
            assert operation.get("operationId"), (method, path)
            assert operation.get("summary"), (method, path)
            for parameter in operation.get("parameters", []):
                assert parameter["required"], (method, path)
