import pytest

APPROVE = {
    "decision": "approve",
    "payout": "420.00",
    "explanation": "The delay was long enough and the receipts are in order.",
    "policy_section": "3. Trip Delay",
}


def start(client, claim_id="CLM-1001"):
    return client.post(f"/api/claims/{claim_id}/start")


def decide(client, body, claim_id="CLM-1001"):
    return client.post(f"/api/claims/{claim_id}/decision", json=body)


def pay(client, amount, claim_id="CLM-1001"):
    return client.post(f"/api/claims/{claim_id}/payment", json={"amount": amount})


def status(client, claim_id="CLM-1001"):
    return client.get(f"/api/claims/{claim_id}").json()["status"]


def test_start_and_release(client):
    assert start(client).json()["status"] == "in_progress"
    assert start(client).status_code == 409
    assert client.post("/api/claims/CLM-1001/release").json()["status"] == "waiting"
    assert client.post("/api/claims/CLM-1001/release").status_code == 409


def test_unknown_claim_is_404(client):
    for path in ("start", "release"):
        assert client.post(f"/api/claims/CLM-0000/{path}").status_code == 404
    assert client.get("/api/claims/CLM-0000/steps").status_code == 404
    step = {"kind": "reply", "text": "Done"}
    assert client.post("/api/claims/CLM-0000/steps", json=step).status_code == 404
    assert decide(client, APPROVE, "CLM-0000").status_code == 404
    assert pay(client, "420.00", "CLM-0000").status_code == 404


def test_steps_come_back_oldest_first(client):
    steps = [
        {"kind": "tool_call", "text": "get_claim CLM-1001"},
        {"kind": "tool_result", "text": "A trip delay claim"},
        {"kind": "reply", "text": "Approved"},
    ]
    for step in steps:
        assert client.post("/api/claims/CLM-1001/steps", json=step).json() == step
    assert client.get("/api/claims/CLM-1001/steps").json() == steps
    assert client.get("/api/claims/CLM-1002/steps").json() == []


def test_approve_and_pay_within_the_limit(client):
    start(client)
    decided = decide(client, APPROVE).json()
    assert decided["status"] == "decided"
    assert decided["decision"]["payout"] == "420.00"
    assert decided["payment"] is None
    paid = pay(client, "420.00").json()
    assert paid["payment"] == {"amount": "420.00"}
    assert paid["status"] == "decided"
    summary = client.get("/api/claims").json()[0]
    assert (summary["decision"], summary["payout"]) == ("approve", "420.00")


def test_payout_over_the_limit_waits_for_sign_off(client):
    start(client)
    decided = decide(client, {**APPROVE, "payout": "1500.00"}).json()
    assert decided["status"] == "awaiting_sign_off"
    blocked = pay(client, "1500.00")
    assert blocked.status_code == 403
    assert (
        blocked.json()["detail"]
        == "A payout over $1,000.00 needs a handler's sign-off."
    )
    assert pay(client, "900.00").status_code == 403
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["status"] == "awaiting_sign_off"
    assert claim["payment"] is None


def test_payout_of_exactly_the_limit_is_paid(client):
    start(client)
    decided = decide(client, {**APPROVE, "payout": "1000.00"}).json()
    assert decided["status"] == "decided"
    assert pay(client, "1000.00").json()["payment"] == {"amount": "1000.00"}


def test_payout_is_rounded_to_the_cent(client):
    start(client)
    decided = decide(client, {**APPROVE, "payout": "420.005"}).json()
    assert decided["decision"]["payout"] == "420.01"


@pytest.mark.parametrize("verdict", ["decline", "refer"])
def test_a_claim_that_is_not_approved_cannot_be_paid(client, verdict):
    start(client)
    body = {**APPROVE, "decision": verdict, "payout": "0.00"}
    assert decide(client, body).json()["status"] == "decided"
    assert pay(client, "420.00").status_code == 409


def test_cannot_pay_before_a_decision(client):
    start(client)
    assert pay(client, "420.00").status_code == 409


def test_cannot_pay_the_wrong_amount_or_twice(client):
    start(client)
    decide(client, APPROVE)
    assert pay(client, "400.00").status_code == 409
    assert pay(client, "420.00").status_code == 200
    assert pay(client, "420.00").status_code == 409


def test_decision_needs_a_claim_in_progress(client):
    assert decide(client, APPROVE).status_code == 409
    start(client)
    assert decide(client, APPROVE).status_code == 200
    assert decide(client, APPROVE).status_code == 409


@pytest.mark.parametrize(
    "changes",
    [
        {"decision": "decline", "payout": "10.00"},
        {"decision": "refer", "payout": "10.00"},
        {"payout": "0.00"},
        {"payout": "0.004"},
        {"payout": "-5.00"},
        {"explanation": ""},
        {"policy_section": ""},
        {"decision": "pay"},
    ],
)
def test_invalid_decisions_are_422(client, changes):
    start(client)
    assert decide(client, {**APPROVE, **changes}).status_code == 422
    assert status(client) == "in_progress"
