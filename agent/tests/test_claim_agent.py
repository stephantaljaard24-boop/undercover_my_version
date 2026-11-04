import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from agent.tests.stubs import FlakyModel, backend_over, call, script
from agent.undercover import claim_agent
from agent.undercover.tools import claim_tools
from backend import store
from backend.main import app
from backend.models import SectionRef

APPROVE = {
    "decision": "approve",
    "payout": "420.00",
    "explanation": "The delay was long enough and the receipts are in order.",
    "policy_section": "3. Trip Delay",
}


def tools_of(backend):
    return {tool.name: tool for tool in claim_tools(backend)}


def kinds(db, claim_id):
    return [step.kind for step in store.steps(db, claim_id)]


def test_tools_read_through_the_backend(backend):
    tools = tools_of(backend)
    assert "My flight home from Rome" in tools["get_claim"].invoke(
        {"claim_id": "CLM-1001"}
    )
    assert "premium" in tools["get_policy"].invoke({"policy_id": "POL-2001"})
    assert "CLM-0412" in tools["get_customer"].invoke({"customer_id": "CUS-3001"})
    contents = tools["get_contents"].invoke({"document": "claims_manual"})
    assert "9. Repeat claims" in contents


def test_reading_a_section_records_it(backend, db):
    text = tools_of(backend)["read_section"].invoke(
        {"claim_id": "CLM-1001", "document": "claims_manual", "section": "9"}
    )
    assert text.startswith("## 9. Repeat claims")
    assert store.reads(db, "CLM-1001") == [
        SectionRef(document="claims_manual", section="9")
    ]


def test_tools_pass_on_a_refusal(backend):
    tools = tools_of(backend)
    assert tools["get_claim"].invoke({"claim_id": "CLM-0000"}) == (
        "Refused (404): CLM-0000 not found"
    )
    missing = tools["read_section"].invoke(
        {"claim_id": "CLM-1001", "document": "claims_manual", "section": "99"}
    )
    assert missing.startswith("Refused (404)")


def test_tools_raise_on_a_backend_error(client):
    class Failing(TestClient):
        def request(self, *args, **kwargs):
            response = super().request(*args, **kwargs)
            response.status_code = 500
            return response

    tools = tools_of(backend_over(Failing(app)))
    with pytest.raises(Exception, match="500"):
        tools["get_claim"].invoke({"claim_id": "CLM-1001"})


def test_approve_and_pay(backend, db):
    llm = script(
        call("get_claim", claim_id="CLM-1001"),
        call("record_decision", claim_id="CLM-1001", **APPROVE),
        call("pay_claim", claim_id="CLM-1001", amount="420.00"),
        AIMessage(content="Approved for $420.00."),
    )
    line = claim_agent.work_claim(backend, "CLM-1001", llm)
    assert line == "CLM-1001: approve $420.00, paid"
    claim = backend.claim("CLM-1001")
    assert claim.status == "decided"
    assert claim.payment is not None
    assert claim.payment.amount == "420.00"
    steps = store.steps(db, "CLM-1001")
    assert [s.kind for s in steps] == [
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "reply",
    ]
    assert steps[0].text == 'get_claim {"claim_id": "CLM-1001"}'
    assert steps[1].text.endswith("...")
    assert steps[3].text == "Decision recorded. The claim is now decided."
    assert steps[-1].text == "Approved for $420.00."


def test_payout_over_the_limit_is_blocked(backend, db):
    llm = script(
        call(
            "record_decision", claim_id="CLM-1003", **{**APPROVE, "payout": "1500.00"}
        ),
        call("pay_claim", claim_id="CLM-1003", amount="1500.00"),
        AIMessage(content="Approved, payment waiting for sign-off."),
    )
    line = claim_agent.work_claim(backend, "CLM-1003", llm)
    assert line == "CLM-1003: approve $1500.00, payment waiting for sign-off"
    claim = backend.claim("CLM-1003")
    assert claim.status == "awaiting_sign_off"
    assert claim.payment is None
    assert "needs a handler's sign-off" in store.steps(db, "CLM-1003")[3].text


def test_decline_and_refer(backend):
    decline = {**APPROVE, "decision": "decline", "payout": "0.00"}
    refer = {**decline, "decision": "refer"}
    llm = script(
        call("record_decision", claim_id="CLM-1001", **decline),
        AIMessage(content="Declined."),
        call("record_decision", claim_id="CLM-1002", **refer),
        AIMessage(content="Referred."),
    )
    assert claim_agent.work_claim(backend, "CLM-1001", llm) == "CLM-1001: decline"
    assert claim_agent.work_claim(backend, "CLM-1002", llm) == "CLM-1002: refer"


def test_approved_but_not_paid(backend):
    llm = script(
        call("record_decision", claim_id="CLM-1001", **APPROVE),
        AIMessage(content="Approved."),
    )
    line = claim_agent.work_claim(backend, "CLM-1001", llm)
    assert line == "CLM-1001: approve $420.00, not paid"


def test_the_helper_looks_up_sections(backend, db):
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
    claim_agent.work_claim(backend, "CLM-1001", llm)
    assert [(r.document, r.section) for r in store.reads(db, "CLM-1001")] == [
        ("claims_manual", "9"),
        ("policy_wording", "3"),
    ]


def test_a_failing_claim_goes_back_and_a_second_failure_leaves_it(backend, db):
    line = claim_agent.work_claim(backend, "CLM-1001", script())
    assert line == "CLM-1001: failed (RuntimeError: model is down), back in the queue"
    assert backend.claim("CLM-1001").status == "waiting"
    line = claim_agent.work_claim(backend, "CLM-1001", script())
    assert line == (
        "CLM-1001: failed again (RuntimeError: model is down), left for a handler"
    )
    assert backend.claim("CLM-1001").status == "needs_handler"
    assert kinds(db, "CLM-1001") == ["error", "error"]
    line = claim_agent.work_claim(backend, "CLM-1001", script())
    assert line.startswith("CLM-1001: not started")


def test_a_model_that_fails_once_is_retried(backend):
    llm = FlakyModel(
        messages=iter(
            [
                call("record_decision", claim_id="CLM-1001", **APPROVE),
                call("pay_claim", claim_id="CLM-1001", amount="420.00"),
                AIMessage(content="Approved."),
            ]
        )
    )
    line = claim_agent.work_claim(backend, "CLM-1001", llm)
    assert line == "CLM-1001: approve $420.00, paid"


def test_a_tool_that_fails_once_is_retried(client, db):
    failures = []

    class FlakyOnce(TestClient):
        def request(self, method, url, *args, **kwargs):
            response = super().request(method, url, *args, **kwargs)
            if method == "GET" and str(url).endswith("/CLM-1001") and not failures:
                failures.append(url)
                response.status_code = 500
            return response

    llm = script(
        call("get_claim", claim_id="CLM-1001"),
        call("record_decision", claim_id="CLM-1001", **APPROVE),
        AIMessage(content="Approved."),
    )
    line = claim_agent.work_claim(backend_over(FlakyOnce(app)), "CLM-1001", llm)
    assert line == "CLM-1001: approve $420.00, not paid"
    assert "My flight home from Rome" in store.steps(db, "CLM-1001")[1].text


def test_a_runaway_loop_is_cut_off(backend, monkeypatch):
    monkeypatch.setattr("agent.harness.agents.MODEL_CALL_LIMIT", 2)
    llm = script(
        *[call("get_claim", call_id=str(n), claim_id="CLM-1001") for n in range(5)]
    )
    line = claim_agent.work_claim(backend, "CLM-1001", llm)
    assert "ModelCallLimitExceededError" in line
    assert backend.claim("CLM-1001").status == "waiting"


def test_claim_without_a_decision_goes_back_to_waiting(backend, db):
    llm = script(AIMessage(content="I am not sure."))
    line = claim_agent.work_claim(backend, "CLM-1001", llm)
    assert line == (
        "CLM-1001: failed (the agent ended without a decision), back in the queue"
    )
    assert backend.claim("CLM-1001").status == "waiting"
    last = store.steps(db, "CLM-1001")[-1]
    assert (last.kind, last.text) == (
        "error",
        "Attempt 1 failed: the agent ended without a decision",
    )


def test_a_failure_after_the_approval_is_paid_once(backend):
    llm = script(call("record_decision", claim_id="CLM-1001", **APPROVE))
    line = claim_agent.work_claim(backend, "CLM-1001", llm)
    assert line == (
        "CLM-1001: approve $420.00, paid (the agent then failed: "
        "RuntimeError: model is down)"
    )
    claim = backend.claim("CLM-1001")
    assert claim.status == "decided"
    assert claim.payment is not None
    assert claim.payment.amount == "420.00"


def test_a_failure_after_an_approval_over_the_limit_leaves_the_payment(backend):
    big = {**APPROVE, "payout": "1500.00"}
    llm = script(call("record_decision", claim_id="CLM-1003", **big))
    line = claim_agent.work_claim(backend, "CLM-1003", llm)
    assert line.startswith("CLM-1003: approve $1500.00, payment waiting for sign-off")
    claim = backend.claim("CLM-1003")
    assert claim.status == "awaiting_sign_off"
    assert claim.payment is None


def test_a_failure_after_a_decline_keeps_the_decision(backend):
    decline = {**APPROVE, "decision": "decline", "payout": "0.00"}
    llm = script(call("record_decision", claim_id="CLM-1001", **decline))
    line = claim_agent.work_claim(backend, "CLM-1001", llm)
    assert line.startswith("CLM-1001: decline (the agent")
    assert backend.claim("CLM-1001").status == "decided"


def test_system_prompt_is_the_claim_instructions(backend):
    llm = script(AIMessage(content="Done."))
    claim_agent.run_helper(backend, "CLM-1001", "thread-1", llm)
    first = llm.seen[0][0]
    assert first.type == "system"
    assert first.content == backend.claim_instructions()
    assert llm.seen[0][1].content == "Decide claim CLM-1001."
