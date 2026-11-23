import httpx
import pytest

from backend import agent_client, db, rules, store
from backend.agent_client import notify_signed_off
from backend.tests.test_workflow import APPROVE, decide, pay, start, status

OVER_THE_LIMIT = {**APPROVE, "payout": "1500.00"}


def sign_off(client, handler_id="HND-01", claim_id="CLM-1001"):
    body = {"handler_id": handler_id}
    return client.post(f"/api/claims/{claim_id}/sign-off", json=body)


def hold(client, claim_id="CLM-1001"):
    """Put a claim at the point where it waits for a handler."""
    start(client, claim_id)
    decide(client, OVER_THE_LIMIT, claim_id)


def test_the_handlers_are_listed_without_their_emails(client):
    handlers = client.get("/api/handlers").json()
    assert [h["name"] for h in handlers] == [
        "Dana Whitfield",
        "Marcus Oyelaran",
        "Priya Raman",
    ]
    assert handlers[0] == {
        "handler_id": "HND-01",
        "name": "Dana Whitfield",
        "role": "Senior Claims Handler",
        "can_approve_over_limit": True,
    }


def test_a_sign_off_puts_the_claim_back_in_progress_and_tells_the_agent(
    client, notified
):
    hold(client)
    assert status(client) == "awaiting_sign_off"
    assert pay(client, "1500.00").status_code == 403
    signed = sign_off(client).json()
    assert signed["status"] == "in_progress"
    assert signed["sign_off"]["handler_id"] == "HND-01"
    assert signed["sign_off"]["signed_off_by"] == "Dana Whitfield"
    assert signed["sign_off"]["signed_off_at"]
    assert signed["payment"] is None
    assert notified == ["CLM-1001"]


def test_the_payment_records_who_signed_off_and_when(client):
    hold(client)
    signed = sign_off(client, "HND-03").json()["sign_off"]
    paid = pay(client, "1500.00").json()
    assert paid["status"] == "decided"
    assert paid["payment"] == {
        "amount": "1500.00",
        "signed_off_by": "Priya Raman",
        "signed_off_at": signed["signed_off_at"],
    }
    assert pay(client, "1500.00").json() == paid


def test_a_second_sign_off_changes_nothing(client, notified):
    hold(client)
    first = sign_off(client, "HND-01").json()
    assert sign_off(client, "HND-02").json() == first
    assert notified == ["CLM-1001"]


def test_a_sign_off_is_refused_for_an_unknown_handler_or_claim(client, notified):
    hold(client)
    assert sign_off(client, "HND-99").status_code == 404
    assert sign_off(client, "HND-01", "CLM-0000").status_code == 404
    assert status(client) == "awaiting_sign_off"
    assert notified == []


def test_a_handler_who_may_not_approve_cannot_sign_off(client, monkeypatch):
    real = rules.load_json
    handlers = [{**h, "can_approve_over_limit": False} for h in real("handlers.json")]
    monkeypatch.setattr(
        rules,
        "load_json",
        lambda name: handlers if name == "handlers.json" else real(name),
    )
    hold(client)
    assert sign_off(client).status_code == 403
    assert status(client) == "awaiting_sign_off"


def test_only_a_claim_waiting_for_sign_off_can_be_signed_off(client, notified):
    assert sign_off(client).status_code == 409
    start(client)
    assert sign_off(client).status_code == 409
    decide(client, APPROVE)
    assert sign_off(client).status_code == 409
    assert notified == []


def test_the_agent_is_told_only_after_the_sign_off_is_saved(client, monkeypatch):
    seen = []

    def check(claim_id):
        with db.engine().connect() as conn:
            seen.append(store.claim_detail(conn, claim_id).sign_off is not None)

    monkeypatch.setattr(agent_client, "notify_signed_off", check)
    hold(client)
    sign_off(client)
    assert seen == [True]


def test_the_sign_off_stands_when_the_agent_cannot_be_reached(client, monkeypatch):
    def unreachable(*_args, **_kwargs):
        raise httpx.ConnectError("the agent is not running")

    monkeypatch.setattr(agent_client, "notify_signed_off", notify_signed_off)
    monkeypatch.setattr(httpx, "post", unreachable)
    hold(client)
    response = sign_off(client)
    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (None, "http://127.0.0.1:8002"),
        ("", "http://127.0.0.1:8002"),
        ("http://127.0.0.1:8003", "http://127.0.0.1:8003"),
    ],
)
def test_the_agents_address_is_in_the_environment(monkeypatch, configured, expected):
    calls = []
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: calls.append(url))
    if configured is None:
        monkeypatch.delenv("UNDERCOVER_AGENT", raising=False)
    else:
        monkeypatch.setenv("UNDERCOVER_AGENT", configured)
    notify_signed_off("CLM-1001")
    assert calls == [f"{expected}/api/claims/CLM-1001/resume"]
