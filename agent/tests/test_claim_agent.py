import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from sqlalchemy import func, select

from agent.harness import graphs
from agent.tests.stubs import (
    FlakyModel,
    Killed,
    backend_over,
    call,
    decision_call,
    script,
)
from agent.undercover.backend import Backend
from agent.undercover.claim_agent import ClaimAgent
from agent.undercover.claim_graph import build_claim_graph
from agent.undercover.tools import claim_tools
from backend import rules, schema, store
from backend.db import engine
from backend.main import app
from backend.models import SectionRef

COVERED = AIMessage(content="The delay is covered.")


def approval(claim_id="CLM-1001", **changes):
    """What the model says on a claim it approves: a look at it, a reply, a decision."""
    return [call("get_claim", claim_id=claim_id), COVERED, decision_call(**changes)]


def work(make_claims, llm, claim_id="CLM-1001"):
    return make_claims(llm).work_claim(claim_id)


def sign_off(claim_id):
    """A handler signs the claim off, which the dashboard does through the backend."""
    with engine().connect() as conn:
        store.add_sign_off(conn, claim_id, rules.signing_handler("HND-01"))


def tools_of(backend):
    return {tool.name: tool for tool in claim_tools(backend)}


def kinds(db, claim_id):
    return [step.kind for step in store.steps(db, claim_id)]


def count(db, table):
    return db.execute(select(func.count()).select_from(table)).scalar_one()


def test_the_claim_agent_has_tools_to_look_things_up_and_work_out_a_payout(backend):
    assert set(tools_of(backend)) == {
        "get_claim",
        "get_policy",
        "get_customer",
        "get_contents",
        "read_section",
        "calculate_payout",
    }


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


def test_approve_and_pay(backend, db, make_claims, saver):
    line = work(make_claims, script(*approval()))
    assert line == "CLM-1001: approve $420.00, paid"
    claim = backend.claim("CLM-1001")
    assert claim.status == "decided"
    assert claim.payment is not None
    assert claim.payment.amount == "420.00"
    assert count(db, schema.decisions) == count(db, schema.payments) == 1
    steps = store.steps(db, "CLM-1001")
    assert [s.kind for s in steps] == [
        "tool_call",
        "tool_result",
        "reply",
        "tool_call",
        "reply",
        "reply",
    ]
    assert steps[0].text == 'get_claim {"claim_id": "CLM-1001"}'
    assert steps[1].text.endswith("...")
    assert steps[3].text.startswith("ClaimDecision {")
    assert [s.text for s in steps[4:]] == ["Decision recorded.", "Paid $420.00."]
    saved = saver.get_tuple({"configurable": {"thread_id": claim.thread_id}})
    assert saved is not None
    assert saved.checkpoint["channel_values"]["decision"] == "approve"
    assert saved.checkpoint["channel_values"]["payout"] == "420.00"


def test_a_payout_over_the_limit_waits_for_a_sign_off_and_is_then_paid_once(
    client, backend, db, make_claims
):
    llm = script(*approval("CLM-1003", payout="1500.00"))
    line = work(make_claims, llm, "CLM-1003")
    assert line == "CLM-1003: approve $1500.00, payment waiting for sign-off"
    claim = backend.claim("CLM-1003")
    thread = claim.thread_id
    assert claim.status == "awaiting_sign_off"
    assert claim.payment is None
    waiting = "Decision recorded. The payment is waiting for a handler's sign-off."
    assert store.steps(db, "CLM-1003")[-1].text == waiting
    assert make_claims(script()).carry_on("CLM-1003") == (
        "CLM-1003: nothing to carry on (awaiting_sign_off)"
    )

    sign_off("CLM-1003")
    restarted = make_claims(script())
    assert restarted.carry_on("CLM-1003") == "CLM-1003: approve $1500.00, paid"
    claim = backend.claim("CLM-1003")
    assert claim.status == "decided"
    assert claim.thread_id == thread
    assert count(db, schema.payments) == 1
    assert restarted.carry_on("CLM-1003").startswith("CLM-1003: nothing to carry on")
    assert store.steps(db, "CLM-1003")[-1].text == "Paid $1500.00."


def test_the_service_only_carries_on_a_signed_off_claim(client, backend, make_claims):
    work(make_claims, script(*approval("CLM-1003", payout="1500.00")), "CLM-1003")
    waiting = make_claims(script()).carry_on("CLM-1003", paused_only=True)
    assert waiting.startswith("CLM-1003: nothing to carry on")
    sign_off("CLM-1003")
    paid = make_claims(script()).carry_on("CLM-1003", paused_only=True)
    assert paid == "CLM-1003: approve $1500.00, paid"


def test_a_sign_off_before_the_graph_pauses_is_not_missed(client, checkpoints):
    class SignsOffAtOnce(Backend):
        def record_decision(
            self, claim_id, decision, payout, explanation, policy_section
        ):
            claim = super().record_decision(
                claim_id, decision, payout, explanation, policy_section
            )
            sign_off(claim_id)
            return claim

    quick = backend_over(client, SignsOffAtOnce)
    llm = script(*approval("CLM-1003", payout="1500.00"))
    line = ClaimAgent(quick, checkpoints, llm).work_claim("CLM-1003")
    assert line == "CLM-1003: approve $1500.00, paid"


def test_a_claim_stopped_partway_carries_on_from_its_last_step(
    backend, db, make_claims
):
    with pytest.raises(Killed):
        work(make_claims, script(call("get_claim", claim_id="CLM-1001"), Killed()))
    stopped = backend.claim("CLM-1001")
    assert stopped.status == "in_progress"
    assert kinds(db, "CLM-1001") == ["tool_call", "tool_result"]

    line = make_claims(script(COVERED, decision_call())).carry_on("CLM-1001")
    assert line == "CLM-1001: approve $420.00, paid"
    claim = backend.claim("CLM-1001")
    assert claim.thread_id == stopped.thread_id
    assert store.claim_row(db, "CLM-1001")["attempts"] == 0
    assert count(db, schema.decisions) == 1
    assert kinds(db, "CLM-1001") == [
        "tool_call",
        "tool_result",
        "reply",
        "tool_call",
        "reply",
        "reply",
    ]


def test_a_claim_stopped_before_its_first_step_starts_on_the_same_thread(
    backend, make_claims
):
    with pytest.raises(Killed):
        work(make_claims, script(Killed()))
    thread = backend.claim("CLM-1001").thread_id
    line = make_claims(script(*approval())).carry_on("CLM-1001")
    assert line == "CLM-1001: approve $420.00, paid"
    assert backend.claim("CLM-1001").thread_id == thread


def test_a_claim_that_fails_before_its_decision_starts_afresh(backend, db, make_claims):
    line = work(make_claims, script())
    assert line == "CLM-1001: failed (RuntimeError: model is down), back in the queue"
    failed = backend.claim("CLM-1001")
    assert failed.status == "waiting"
    assert store.claim_row(db, "CLM-1001")["attempts"] == 1

    assert work(make_claims, script(*approval())) == "CLM-1001: approve $420.00, paid"
    assert backend.claim("CLM-1001").thread_id != failed.thread_id


def test_a_second_failure_leaves_the_claim_for_a_handler(backend, db, make_claims):
    work(make_claims, script())
    line = work(make_claims, script())
    assert line == (
        "CLM-1001: failed again (RuntimeError: model is down), left for a handler"
    )
    assert backend.claim("CLM-1001").status == "needs_handler"
    assert kinds(db, "CLM-1001") == ["error", "error"]
    assert work(make_claims, script()).startswith("CLM-1001: not started")


def test_a_failure_after_the_decision_keeps_the_claim_to_carry_on(
    client, backend, db, checkpoints
):
    class BrokenPay(Backend):
        broken = True

        def pay(self, claim_id, amount):
            if self.broken:
                raise RuntimeError("the backend is down")
            return super().pay(claim_id, amount)

    flaky = backend_over(client, BrokenPay)
    line = ClaimAgent(flaky, checkpoints, script(*approval())).work_claim("CLM-1001")
    assert line == (
        "CLM-1001: approve $420.00, not paid yet (stopped: RuntimeError: "
        "the backend is down; the next run carries on)"
    )
    claim = backend.claim("CLM-1001")
    assert claim.status == "in_progress"
    assert store.claim_row(db, "CLM-1001")["attempts"] == 0

    flaky.broken = False
    line = ClaimAgent(flaky, checkpoints, script()).carry_on("CLM-1001")
    assert line == "CLM-1001: approve $420.00, paid"
    assert backend.claim("CLM-1001").thread_id == claim.thread_id


def test_replaying_the_recording_and_the_payment_changes_nothing(
    backend, db, make_claims, checkpoints
):
    work(make_claims, script(*approval()))
    thread = backend.claim("CLM-1001").thread_id
    config = RunnableConfig(configurable={"thread_id": thread})
    with checkpoints() as saver:
        graph = build_claim_graph(backend, script(), "Instructions", saver)
        history = list(graph.get_state_history(config))
        before_record = next(s for s in history if s.next == ("record",))
        graph.invoke(None, before_record.config)
    assert count(db, schema.decisions) == count(db, schema.payments) == 1
    assert backend.claim("CLM-1001").status == "decided"


def test_decline_and_refer_end_after_the_decision(backend, db, make_claims):
    llm = script(
        COVERED,
        decision_call(decision="decline", payout="0.00"),
        COVERED,
        decision_call(decision="refer", payout="0.00"),
    )
    claims = make_claims(llm)
    assert claims.work_claim("CLM-1001") == "CLM-1001: decline"
    assert claims.work_claim("CLM-1002") == "CLM-1002: refer"
    assert backend.claim("CLM-1001").status == "decided"
    assert store.steps(db, "CLM-1001")[-1].text == "Decision recorded."


def test_the_agent_looks_up_sections(backend, db, make_claims):
    llm = script(
        call("get_contents", document="claims_manual"),
        call(
            "read_section", claim_id="CLM-1001", document="claims_manual", section="9"
        ),
        call(
            "read_section", claim_id="CLM-1001", document="policy_wording", section="3"
        ),
        COVERED,
        decision_call(),
    )
    work(make_claims, llm)
    assert [(r.document, r.section) for r in store.reads(db, "CLM-1001")] == [
        ("claims_manual", "9"),
        ("policy_wording", "3"),
    ]


def test_a_model_that_fails_once_is_retried(make_claims):
    line = work(make_claims, FlakyModel(messages=iter(approval())))
    assert line == "CLM-1001: approve $420.00, paid"


def test_a_decision_that_is_not_valid_is_asked_for_again(backend, make_claims):
    llm = script(COVERED, decision_call(payout="$420"), decision_call())
    assert work(make_claims, llm) == "CLM-1001: approve $420.00, paid"


def test_a_model_that_gives_no_decision_fails_the_attempt(backend, make_claims):
    llm = script(COVERED, COVERED, COVERED, COVERED)
    line = work(make_claims, llm)
    assert line.startswith("CLM-1001: failed (ValueError: The model gave no decision)")
    assert backend.claim("CLM-1001").status == "waiting"


def test_a_tool_that_fails_once_is_retried(client, backend, db, checkpoints):
    failures = []

    class FlakyOnce(TestClient):
        def request(self, method, url, *args, **kwargs):
            response = super().request(method, url, *args, **kwargs)
            if method == "GET" and str(url).endswith("/CLM-1001") and not failures:
                failures.append(url)
                response.status_code = 500
            return response

    flaky = backend_over(FlakyOnce(app))
    line = ClaimAgent(flaky, checkpoints, script(*approval())).work_claim("CLM-1001")
    assert line == "CLM-1001: approve $420.00, paid"
    assert "My flight home from Rome" in store.steps(db, "CLM-1001")[1].text


def test_a_runaway_loop_is_cut_off(backend, make_claims, monkeypatch):
    monkeypatch.setattr(graphs, "MODEL_CALL_LIMIT", 2)
    llm = script(
        *[call("get_claim", call_id=str(n), claim_id="CLM-1001") for n in range(5)]
    )
    line = work(make_claims, llm)
    assert "CallLimitExceeded" in line
    assert backend.claim("CLM-1001").status == "waiting"


def test_the_system_prompt_is_the_claim_instructions(backend, make_claims):
    llm = script(COVERED, decision_call())
    work(make_claims, llm)
    first = llm.seen[0]
    assert first[0].type == "system"
    assert first[0].content == backend.claim_instructions()
    assert first[1].content == "Decide claim CLM-1001."


def test_the_payout_tool_returns_the_calculation(backend):
    lines = [
        {
            "description": "Suitcase",
            "amount": "239.99",
            "quantity": 1,
            "kind": "item",
            "nights": 0,
            "hours": "0",
        }
    ]
    text = tools_of(backend)["calculate_payout"].invoke(
        {
            "claim_id": "CLM-1001",
            "benefit": "baggage",
            "lines": lines,
            "paid_by_others": "100.00",
        }
    )
    assert '"payout": "89.99"' in text
    assert '"needs_sign_off": false' in text


def test_the_payout_tool_passes_on_a_refusal(backend):
    text = tools_of(backend)["calculate_payout"].invoke(
        {
            "claim_id": "CLM-0000",
            "benefit": "baggage",
            "lines": [],
            "paid_by_others": "0.00",
        }
    )
    assert text == "Refused (404): CLM-0000 not found"
