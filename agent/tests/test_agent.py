import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from agent import main, runner, tools
from agent.tests.stubs import FlakyModel, call, script
from backend.main import app

APPROVE = {
    "decision": "approve",
    "payout": "420.00",
    "explanation": "The delay was long enough and the receipts are in order.",
    "policy_section": "3. Trip Delay",
}


def test_tools_read_through_the_api():
    assert "My flight home from Rome" in tools.get_claim.invoke(
        {"claim_id": "CLM-1001"}
    )
    assert "premium" in tools.get_policy.invoke({"policy_id": "POL-2001"})
    assert "CLM-0412" in tools.get_customer.invoke({"customer_id": "CUS-3001"})
    contents = tools.get_contents.invoke({"document": "claims_manual"})
    assert "9. Repeat claims" in contents


def test_reading_a_section_records_it(client):
    text = tools.read_section.invoke(
        {"claim_id": "CLM-1001", "document": "claims_manual", "section": "9"}
    )
    assert text.startswith("## 9. Repeat claims")
    assert client.get("/api/claims/CLM-1001/reads").json() == [
        {"document": "claims_manual", "section": "9", "title": "Repeat claims"}
    ]


def test_tools_pass_on_a_refusal():
    assert tools.get_claim.invoke({"claim_id": "CLM-0000"}).startswith("Refused (404)")
    missing = tools.read_section.invoke(
        {"claim_id": "CLM-1001", "document": "claims_manual", "section": "99"}
    )
    assert missing.startswith("Refused (404)")


def test_tools_raise_on_a_backend_error(monkeypatch):
    class Failing(TestClient):
        def get(self, *args, **kwargs):
            response = super().get(*args, **kwargs)
            response.status_code = 500
            return response

    monkeypatch.setattr(tools, "backend", lambda: Failing(app))
    with pytest.raises(Exception, match="500"):
        tools.get_claim.invoke({"claim_id": "CLM-1001"})


def test_approve_and_pay(client):
    llm = script(
        call("get_claim", claim_id="CLM-1001"),
        call("record_decision", claim_id="CLM-1001", **APPROVE),
        call("pay_claim", claim_id="CLM-1001", amount="420.00"),
        AIMessage(content="Approved for $420.00."),
    )
    assert runner.work_claim("CLM-1001", llm) == "CLM-1001: approve $420.00, paid"
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["status"] == "decided"
    assert claim["payment"] == {"amount": "420.00"}
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert [s["kind"] for s in steps] == [
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "reply",
    ]
    assert steps[0]["text"] == 'get_claim {"claim_id": "CLM-1001"}'
    assert steps[1]["text"].endswith("...")
    assert steps[3]["text"] == "Decision recorded. The claim is now decided."
    assert steps[-1]["text"] == "Approved for $420.00."


def test_payout_over_the_limit_is_blocked(client):
    llm = script(
        call(
            "record_decision", claim_id="CLM-1003", **{**APPROVE, "payout": "1500.00"}
        ),
        call("pay_claim", claim_id="CLM-1003", amount="1500.00"),
        AIMessage(content="Approved, payment waiting for sign-off."),
    )
    line = runner.work_claim("CLM-1003", llm)
    assert line == "CLM-1003: approve $1500.00, payment waiting for sign-off"
    claim = client.get("/api/claims/CLM-1003").json()
    assert claim["status"] == "awaiting_sign_off"
    assert claim["payment"] is None
    steps = client.get("/api/claims/CLM-1003/steps").json()
    assert "needs a handler's sign-off" in steps[3]["text"]


def test_decline_and_refer(client):
    decline = {**APPROVE, "decision": "decline", "payout": "0.00"}
    refer = {**decline, "decision": "refer"}
    llm = script(
        call("record_decision", claim_id="CLM-1001", **decline),
        AIMessage(content="Declined."),
        call("record_decision", claim_id="CLM-1002", **refer),
        AIMessage(content="Referred."),
    )
    assert runner.work_claim("CLM-1001", llm) == "CLM-1001: decline"
    assert runner.work_claim("CLM-1002", llm) == "CLM-1002: refer"


def test_approved_but_not_paid(client):
    llm = script(
        call("record_decision", claim_id="CLM-1001", **APPROVE),
        AIMessage(content="Approved."),
    )
    assert runner.work_claim("CLM-1001", llm) == "CLM-1001: approve $420.00, not paid"


def test_the_helper_looks_up_sections(client):
    llm = script(
        call("get_contents", document="claims_manual"),
        call(
            "read_section", claim_id="CLM-1001", document="claims_manual", section="9"
        ),
        call(
            "read_section", claim_id="CLM-1001", document="policy_wording", section="3"
        ),
        AIMessage(content="Done."),
    )
    runner.work_claim("CLM-1001", llm)
    reads = client.get("/api/claims/CLM-1001/reads").json()
    assert [(r["document"], r["section"]) for r in reads] == [
        ("claims_manual", "9"),
        ("policy_wording", "3"),
    ]


def test_a_failing_claim_goes_back_and_a_second_failure_leaves_it(client):
    line = runner.work_claim("CLM-1001", script())
    assert line == ("CLM-1001: failed (RuntimeError: model is down), back in the queue")
    assert client.get("/api/claims/CLM-1001").json()["status"] == "waiting"
    line = runner.work_claim("CLM-1001", script())
    assert line == (
        "CLM-1001: failed again (RuntimeError: model is down), left for a handler"
    )
    assert client.get("/api/claims/CLM-1001").json()["status"] == "needs_handler"
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert [s["kind"] for s in steps] == ["error", "error"]
    assert runner.work_claim("CLM-1001", script()).startswith("CLM-1001: not started")


def test_a_model_that_fails_once_is_retried(client):
    llm = FlakyModel(
        messages=iter(
            [
                call("record_decision", claim_id="CLM-1001", **APPROVE),
                call("pay_claim", claim_id="CLM-1001", amount="420.00"),
                AIMessage(content="Approved."),
            ]
        )
    )
    assert runner.work_claim("CLM-1001", llm) == "CLM-1001: approve $420.00, paid"


def test_a_tool_that_fails_once_is_retried(client, monkeypatch):
    real = TestClient(app)
    calls = []

    class FlakyOnce(TestClient):
        def get(self, url, *args, **kwargs):
            response = real.get(url, *args, **kwargs)
            if url == "/api/claims/CLM-1001" and not calls:
                calls.append(url)
                response.status_code = 500
            return response

    monkeypatch.setattr(tools, "backend", lambda: FlakyOnce(app))
    llm = script(
        call("get_claim", claim_id="CLM-1001"),
        call("record_decision", claim_id="CLM-1001", **APPROVE),
        AIMessage(content="Approved."),
    )
    assert runner.work_claim("CLM-1001", llm) == "CLM-1001: approve $420.00, not paid"
    steps = real.get("/api/claims/CLM-1001/steps").json()
    assert "My flight home from Rome" in steps[1]["text"]


def test_a_runaway_loop_is_cut_off(client, monkeypatch):
    monkeypatch.setattr(main, "MODEL_CALL_LIMIT", 2)
    llm = script(
        *[call("get_claim", call_id=str(n), claim_id="CLM-1001") for n in range(5)]
    )
    line = runner.work_claim("CLM-1001", llm)
    assert "ModelCallLimitExceededError" in line
    assert client.get("/api/claims/CLM-1001").json()["status"] == "waiting"


def test_claim_without_a_decision_goes_back_to_waiting(client):
    llm = script(AIMessage(content="I am not sure."))
    assert runner.work_claim("CLM-1001", llm) == (
        "CLM-1001: failed (the agent ended without a decision), back in the queue"
    )
    assert client.get("/api/claims/CLM-1001").json()["status"] == "waiting"
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert steps[-1] == {
        "kind": "error",
        "text": "Attempt 1 failed: the agent ended without a decision",
    }


def test_a_failure_after_the_approval_is_paid_once(client):
    llm = script(call("record_decision", claim_id="CLM-1001", **APPROVE))
    line = runner.work_claim("CLM-1001", llm)
    assert line == (
        "CLM-1001: approve $420.00, paid (the agent then failed: "
        "RuntimeError: model is down)"
    )
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["status"] == "decided"
    assert claim["payment"] == {"amount": "420.00"}


def test_a_failure_after_an_approval_over_the_limit_leaves_the_payment(client):
    big = {**APPROVE, "payout": "1500.00"}
    llm = script(call("record_decision", claim_id="CLM-1003", **big))
    line = runner.work_claim("CLM-1003", llm)
    assert line.startswith("CLM-1003: approve $1500.00, payment waiting for sign-off")
    claim = client.get("/api/claims/CLM-1003").json()
    assert claim["status"] == "awaiting_sign_off"
    assert claim["payment"] is None


def test_a_failure_after_a_decline_keeps_the_decision(client):
    decline = {**APPROVE, "decision": "decline", "payout": "0.00"}
    llm = script(call("record_decision", claim_id="CLM-1001", **decline))
    assert runner.work_claim("CLM-1001", llm).startswith("CLM-1001: decline (the agent")
    assert client.get("/api/claims/CLM-1001").json()["status"] == "decided"


def test_system_prompt_is_the_claim_instructions(client):
    llm = script(AIMessage(content="Done."))
    main.run("CLM-1001", "thread-1", llm)
    first = llm.seen[0][0]
    assert first.type == "system"
    assert first.content == client.get("/api/instructions/claim").text
    assert llm.seen[0][1].content == "Decide claim CLM-1001."


def test_model_name(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    assert main.model().model_name == "deepseek/deepseek-v4.1-flash"
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    assert main.model().model_name == "openrouter/free"
