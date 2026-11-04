import pytest
from fastapi.testclient import TestClient

from agent.harness.todos import TodoItem
from agent.tests.stubs import backend_over
from agent.undercover.backend import Backend, Refused
from backend import store
from backend.main import app


def test_it_asks_for_claims(backend):
    assert backend.claim("CLM-1001").status == "waiting"
    assert "My flight home from Rome" in backend.claim_text("CLM-1001")
    waiting = backend.waiting_claims()
    assert len(waiting) == 25
    assert waiting[0].claim_id == "CLM-1001"
    backend.start_claim("CLM-1001")
    assert len(backend.waiting_claims()) == 24


def test_it_records_a_decision_and_a_payment(backend):
    backend.start_claim("CLM-1001")
    claim = backend.record_decision("CLM-1001", "approve", "420.00", "Covered.", "3.")
    assert claim.status == "decided"
    assert claim.decision is not None
    assert claim.decision.payout == "420.00"
    assert backend.pay("CLM-1001", "420.00").payment is not None


def test_it_records_a_failure_and_a_step(backend, db):
    backend.start_claim("CLM-1001")
    backend.add_step("CLM-1001", "reply", "Hello.")
    assert backend.fail_claim("CLM-1001", "broke").status == "waiting"
    assert [s.kind for s in store.steps(db, "CLM-1001")] == ["reply", "error"]


def test_it_reads_documents_and_instructions(backend):
    assert "9. Repeat claims" in backend.contents("claims_manual")
    assert backend.read_section("CLM-1001", "claims_manual", "9").startswith("## 9.")
    assert "premium" in backend.policy_text("POL-2001")
    assert "CLM-0412" in backend.customer_text("CUS-3001")
    assert backend.claim_instructions()
    assert backend.queue_instructions()


def test_it_runs_the_queue(backend, db):
    run_id = backend.start_run(3)
    backend.set_todos(run_id, [TodoItem(text="CLM-1001", status="todo")])
    backend.finish_run(run_id, "Done.")
    run = store.current_run(db)
    assert run is not None
    assert (run.claim_limit, run.summary, run.finished) == (3, "Done.", True)
    assert [(t.text, t.status) for t in run.todos] == [("CLM-1001", "todo")]


def test_a_refusal_is_one_error_with_the_reason(backend):
    with pytest.raises(Refused) as caught:
        backend.claim("CLM-0000")
    assert caught.value.status_code == 404
    assert caught.value.reason == "CLM-0000 not found"
    assert str(caught.value) == "Refused (404): CLM-0000 not found"
    with pytest.raises(Refused, match="409"):
        backend.fail_claim("CLM-1001", "not started")


def test_a_failure_of_the_backend_raises(client):
    class Failing(TestClient):
        def request(self, *args, **kwargs):
            response = super().request(*args, **kwargs)
            response.status_code = 500
            return response

    with pytest.raises(Exception, match="500"):
        backend_over(Failing(app)).claim("CLM-1001")


def test_it_connects_to_the_address_in_the_environment(monkeypatch):
    monkeypatch.setenv("BACKEND_URL", "http://example.test:9")
    with Backend.connect() as backend:
        assert str(backend.client.base_url).startswith("http://example.test:9")
    monkeypatch.delenv("BACKEND_URL")
    with Backend.connect() as backend:
        assert str(backend.client.base_url).startswith("http://localhost:8000")
