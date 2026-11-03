import pytest
from langchain_core.messages import AIMessage, ToolMessage

from agent import queue_run, runner
from agent.__main__ import main as cli
from agent.tests.stubs import ByClaimModel, call, script

DECLINE = {
    "decision": "decline",
    "payout": "0.00",
    "explanation": "The wording does not cover this.",
    "policy_section": "9. General exclusions",
}


@pytest.fixture(autouse=True)
def two_waiting(client):
    """Leave CLM-1001 and CLM-1002 waiting and put the other claims in progress."""
    for number in range(1003, 1026):
        client.post(f"/api/claims/CLM-{number}/start")


def decide(claim_id):
    """A helper's script: record a decline, then reply."""
    return [
        call("record_decision", claim_id=claim_id, **DECLINE),
        AIMessage(content="Done."),
    ]


def todos(*items):
    return call("write_todos", todos=[{"text": t, "status": s} for t, s in items])


def status(client, claim_id):
    return client.get(f"/api/claims/{claim_id}").json()["status"]


def tool_texts(llm):
    return [
        message.text for message in llm.seen[-1] if isinstance(message, ToolMessage)
    ]


def test_a_full_run(client, capsys):
    llm = script(
        call("list_waiting_claims"),
        todos(("CLM-1001", "todo"), ("CLM-1002", "todo")),
        call("work_claim", claim_id="CLM-1001"),
        todos(("CLM-1001", "done"), ("CLM-1002", "in_progress")),
        call("work_claim", claim_id="CLM-1002"),
        todos(("CLM-1001", "done"), ("CLM-1002", "done")),
        call("finish_run", summary="Both claims declined."),
        AIMessage(content="Finished."),
    )
    helpers = ByClaimModel(
        scripts={"CLM-1001": decide("CLM-1001"), "CLM-1002": decide("CLM-1002")}
    )
    assert queue_run.run_queue(llm=llm, claim_llm=helpers) == "Both claims declined."
    run = client.get("/api/runs/current").json()
    assert run["finished"] is True
    assert run["claim_limit"] == 2
    assert run["summary"] == "Both claims declined."
    assert run["todos"] == [
        {"text": "CLM-1001", "status": "done"},
        {"text": "CLM-1002", "status": "done"},
    ]
    assert status(client, "CLM-1001") == status(client, "CLM-1002") == "decided"
    assert capsys.readouterr().out.splitlines() == [
        "CLM-1001: decline",
        "CLM-1002: decline",
        "Both claims declined.",
    ]
    assert "CLM-1001 | " in tool_texts(llm)[0]
    assert tool_texts(llm)[1] == "To-do list saved."


def test_the_cap_stops_the_run_starting_more_claims(client):
    llm = script(
        call("work_claim", claim_id="CLM-1001"),
        call("work_claim", claim_id="CLM-1002"),
        call("finish_run", summary="One claim worked."),
        AIMessage(content="Finished."),
    )
    helpers = ByClaimModel(scripts={"CLM-1001": decide("CLM-1001")})
    queue_run.run_queue(limit=1, llm=llm, claim_llm=helpers)
    assert status(client, "CLM-1001") == "decided"
    assert status(client, "CLM-1002") == "waiting"
    assert "cap of 1 claims is used up" in tool_texts(llm)[1]
    assert client.get("/api/runs/current").json()["claim_limit"] == 1
    assert client.get("/api/runs/current").json()["finished"] is True


def test_one_bad_claim_does_not_stop_the_run(client):
    llm = script(
        call("work_claim", claim_id="CLM-1001"),
        call("work_claim", claim_id="CLM-1002"),
        call("finish_run", summary="One decided."),
        AIMessage(content="Finished."),
    )
    helpers = ByClaimModel(scripts={"CLM-1002": decide("CLM-1002")})
    queue_run.run_queue(limit=2, llm=llm, claim_llm=helpers)
    first, second = tool_texts(llm)[:2]
    assert first == "CLM-1001: failed (RuntimeError: model is down), back in the queue"
    assert second == "CLM-1002: decline"
    assert status(client, "CLM-1001") == "waiting"
    assert status(client, "CLM-1002") == "decided"


def test_a_failed_claim_is_tried_again_and_decided(client):
    down = [TimeoutError("timed out")] * 3
    llm = script(
        call("work_claim", claim_id="CLM-1001"),
        call("work_claim", claim_id="CLM-1001"),
        call("finish_run", summary="Retried once."),
        AIMessage(content="Finished."),
    )
    helpers = ByClaimModel(scripts={"CLM-1001": [*down, *decide("CLM-1001")]})
    queue_run.run_queue(limit=1, llm=llm, claim_llm=helpers)
    assert tool_texts(llm)[0].startswith("CLM-1001: failed (TimeoutError")
    assert tool_texts(llm)[1] == "CLM-1001: decline"
    assert status(client, "CLM-1001") == "decided"
    assert [s["kind"] for s in client.get("/api/claims/CLM-1001/steps").json()][
        0
    ] == "error"


def test_a_claim_that_fails_twice_is_left_for_a_handler(client):
    llm = script(
        call("work_claim", claim_id="CLM-1001"),
        call("work_claim", claim_id="CLM-1001"),
        call("work_claim", claim_id="CLM-1001"),
        todos(("CLM-1001", "left_for_handler")),
        call("work_claim", claim_id="CLM-1002"),
        call("finish_run", summary="One left for a handler."),
        AIMessage(content="Finished."),
    )
    helpers = ByClaimModel(scripts={"CLM-1002": decide("CLM-1002")})
    queue_run.run_queue(limit=2, llm=llm, claim_llm=helpers)
    texts = tool_texts(llm)
    assert (
        texts[1]
        == "CLM-1001: failed again (RuntimeError: model is down), left for a handler"
    )
    assert texts[2] == "Refused: CLM-1001 is needs_handler, not waiting."
    assert status(client, "CLM-1001") == "needs_handler"
    assert status(client, "CLM-1002") == "decided"


def test_finishing_is_refused_while_a_claim_is_missed(client):
    llm = script(
        call("finish_run", summary="Too early."),
        call("work_claim", claim_id="CLM-1001"),
        call("work_claim", claim_id="CLM-1002"),
        call("finish_run", summary="Both declined."),
        AIMessage(content="Finished."),
    )
    helpers = ByClaimModel(
        scripts={"CLM-1001": decide("CLM-1001"), "CLM-1002": decide("CLM-1002")}
    )
    queue_run.run_queue(llm=llm, claim_llm=helpers)
    texts = tool_texts(llm)
    assert texts[0] == (
        "Refused: still waiting and within the cap: CLM-1001, CLM-1002."
        " Work them first."
    )
    assert texts[3] == "Run finished."
    assert client.get("/api/runs/current").json()["summary"] == "Both declined."


def test_a_failed_claim_waiting_for_its_retry_blocks_the_finish(client):
    llm = script(
        call("work_claim", claim_id="CLM-1001"),
        call("finish_run", summary="Too early."),
        AIMessage(content="Giving up."),
    )
    queue_run.run_queue(limit=1, llm=llm, claim_llm=ByClaimModel())
    assert tool_texts(llm)[1].startswith(
        "Refused: still waiting and within the cap: CLM-1001"
    )
    run = client.get("/api/runs/current").json()
    assert run["summary"] == "Giving up."
    assert run["finished"] is True


def test_no_claim_is_decided_twice(client):
    llm = script(
        call("work_claim", claim_id="CLM-1001"),
        call("work_claim", claim_id="CLM-1001"),
        call("work_claim", claim_id="CLM-0000"),
        call("finish_run", summary="Done."),
        AIMessage(content="Finished."),
    )
    helpers = ByClaimModel(scripts={"CLM-1001": decide("CLM-1001")})
    queue_run.run_queue(limit=1, llm=llm, claim_llm=helpers)
    texts = tool_texts(llm)
    assert texts[1] == "Refused: CLM-1001 is decided, not waiting."
    assert texts[2] == "Refused: CLM-0000 was not found."


def test_a_second_decision_from_a_helper_is_refused_by_the_backend(client):
    twice = [
        call("record_decision", claim_id="CLM-1001", **DECLINE),
        call(
            "record_decision", claim_id="CLM-1001", **{**DECLINE, "decision": "refer"}
        ),
        AIMessage(content="Done."),
    ]
    runner.work_claim("CLM-1001", ByClaimModel(scripts={"CLM-1001": twice}))
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["decision"]["decision"] == "decline"
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert "Refused (409)" in steps[3]["text"]


def test_claims_are_worked_one_at_a_time(client):
    both = AIMessage(
        content="",
        tool_calls=[
            {"name": "work_claim", "args": {"claim_id": "CLM-1001"}, "id": "a"},
            {"name": "work_claim", "args": {"claim_id": "CLM-1002"}, "id": "b"},
        ],
    )
    llm = script(
        both, call("finish_run", summary="Both."), AIMessage(content="Finished.")
    )
    helpers = ByClaimModel(
        scripts={"CLM-1001": decide("CLM-1001"), "CLM-1002": decide("CLM-1002")}
    )
    queue_run.run_queue(llm=llm, claim_llm=helpers)
    assert helpers.most_active == 1
    assert status(client, "CLM-1001") == status(client, "CLM-1002") == "decided"


def test_the_queue_agent_sees_only_one_line_for_each_claim(client):
    llm = script(
        call("work_claim", claim_id="CLM-1001"),
        call("work_claim", claim_id="CLM-1002"),
        call("finish_run", summary="Both."),
        AIMessage(content="Finished."),
    )
    helpers = ByClaimModel(
        scripts={"CLM-1001": decide("CLM-1001"), "CLM-1002": decide("CLM-1002")}
    )
    queue_run.run_queue(llm=llm, claim_llm=helpers)
    seen = llm.seen[-1]
    assert [m.type for m in seen] == [
        "system",
        "human",
        "ai",
        "tool",
        "ai",
        "tool",
        "ai",
        "tool",
    ]
    assert [m.content for m in seen if m.type == "tool"][:2] == [
        "CLM-1001: decline",
        "CLM-1002: decline",
    ]
    assert "record_decision" not in "".join(str(m.content) for m in seen)


def test_a_run_that_stops_without_finishing_keeps_the_last_reply(client):
    llm = script(AIMessage(content="I worked what I could."))
    assert queue_run.run_queue(llm=llm) == "I worked what I could."
    run = client.get("/api/runs/current").json()
    assert run["summary"] == "I worked what I could."
    assert run["finished"] is True


def test_the_system_prompt_is_the_queue_instructions(client):
    llm = script(AIMessage(content="Nothing to say."))
    queue_run.run_queue(llm=llm)
    first = llm.seen[0][0]
    assert first.type == "system"
    assert first.content == client.get("/api/instructions/queue").text
    assert "up to 2 claims" in llm.seen[0][1].content


def test_nothing_waiting_means_no_run(client, capsys):
    for number in (1001, 1002):
        client.post(f"/api/claims/CLM-{number}/start")
    assert queue_run.run_queue(llm=script()) == ""
    assert capsys.readouterr().out == "No claims are waiting.\n"
    assert client.get("/api/runs/current").json() is None


def test_command_line(monkeypatch, capsys):
    ran = []
    monkeypatch.setattr("agent.__main__.run_queue", ran.append)
    monkeypatch.setattr(
        "agent.__main__.work_claim", lambda claim_id: f"{claim_id}: done"
    )
    cli([])
    cli(["--limit", "3"])
    cli(["CLM-1001"])
    assert ran == [None, 3]
    assert capsys.readouterr().out == "CLM-1001: done\n"
    with pytest.raises(SystemExit):
        cli(["CLM-1001", "--limit", "3"])
