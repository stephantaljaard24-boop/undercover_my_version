import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from pydantic import Field

from agent import main, runner, tools
from backend.main import app

APPROVE = {
    "decision": "approve",
    "payout": "420.00",
    "explanation": "The delay was long enough and the receipts are in order.",
    "policy_section": "3. Trip Delay",
}


class StubModel(GenericFakeChatModel):
    """A chat model that gives scripted replies in place of a real model."""

    seen: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, *args, **kwargs):
        self.seen.append(messages)
        return super()._generate(messages, *args, **kwargs)


class BrokenModel(StubModel):
    def _generate(self, messages, *args, **kwargs):
        raise RuntimeError("model is down")


def call(name, call_id="1", **args):
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": args, "id": call_id}]
    )


def script(*replies):
    return StubModel(messages=iter(replies))


@pytest.fixture(autouse=True)
def backend_in_process(client, monkeypatch):
    monkeypatch.setattr(tools, "backend", lambda: TestClient(app))
    return client


def test_tools_read_through_the_api():
    assert "My flight home from Rome" in tools.get_claim.invoke(
        {"claim_id": "CLM-1001"}
    )
    assert "premium" in tools.get_policy.invoke({"policy_id": "POL-2001"})
    assert "CLM-0412" in tools.get_customer.invoke({"customer_id": "CUS-3001"})
    assert "Policy Wording" in tools.get_policy_wording.invoke({})


def test_tools_pass_on_a_refusal():
    reply = tools.get_claim.invoke({"claim_id": "CLM-0000"})
    assert reply.startswith("Refused (404)")


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


def test_claim_without_a_decision_goes_back_to_waiting(client):
    llm = script(AIMessage(content="I am not sure."))
    assert (
        runner.work_claim("CLM-1001", llm) == "CLM-1001: no decision, back in the queue"
    )
    assert client.get("/api/claims/CLM-1001").json()["status"] == "waiting"


def test_failure_releases_the_claim(client):
    with pytest.raises(RuntimeError, match="model is down"):
        runner.work_claim("CLM-1001", BrokenModel(messages=iter([])))
    assert client.get("/api/claims/CLM-1001").json()["status"] == "waiting"


def test_queue_works_the_waiting_claims_only(client, capsys):
    for number in range(1003, 1026):
        client.post(f"/api/claims/CLM-{number}/start")
    decline = {**APPROVE, "decision": "decline", "payout": "0.00"}
    llm = script(
        call("record_decision", claim_id="CLM-1001", **decline),
        AIMessage(content="Declined."),
        call("record_decision", claim_id="CLM-1002", **decline),
        AIMessage(content="Declined."),
    )
    assert runner.work_queue(llm) == ["CLM-1001: decline", "CLM-1002: decline"]
    assert capsys.readouterr().out == "CLM-1001: decline\nCLM-1002: decline\n"
    assert client.get("/api/claims/CLM-1003").json()["status"] == "in_progress"


def test_main_runs_one_claim_or_the_queue(client, capsys, monkeypatch):
    monkeypatch.setattr(main, "model", lambda: script(AIMessage(content="Unsure.")))
    runner.main(["CLM-1001"])
    assert capsys.readouterr().out == "CLM-1001: no decision, back in the queue\n"
    for number in range(1001, 1026):
        client.post(f"/api/claims/CLM-{number}/start")
    runner.main([])
    assert capsys.readouterr().out == ""


def test_system_prompt_is_the_backends_instructions(client):
    llm = script(AIMessage(content="Done."))
    main.run("CLM-1001", "thread-1", llm)
    first = llm.seen[0][0]
    assert first.type == "system"
    assert first.content == client.get("/api/instructions").text
    assert llm.seen[0][1].content == "Decide claim CLM-1001."


def test_model_name(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    assert main.model().model_name == "openai/gpt-6-luna"
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    assert main.model().model_name == "openrouter/free"
