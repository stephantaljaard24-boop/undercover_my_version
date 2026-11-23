import pytest

from backend.seed import seed
from backend.tests.test_workflow import APPROVE, decide, pay, start, status


def fail(client, claim_id="CLM-1001", reason="The model timed out"):
    return client.post(f"/api/claims/{claim_id}/fail", json={"reason": reason})


def test_first_failure_sends_the_claim_back_with_an_error_step(client):
    start(client)
    assert fail(client).json()["status"] == "waiting"
    steps = client.get("/api/claims/CLM-1001/steps").json()
    assert steps == [{"kind": "error", "text": "Attempt 1 failed: The model timed out"}]


def test_second_failure_leaves_the_claim_for_a_handler(client):
    for _ in range(2):
        start(client)
        fail(client)
    assert status(client) == "needs_handler"
    assert start(client).status_code == 409
    assert fail(client).status_code == 409
    errors = client.get("/api/claims/CLM-1001/steps").json()
    assert [step["text"][:9] for step in errors] == ["Attempt 1", "Attempt 2"]


def test_only_a_claim_in_progress_can_fail(client):
    assert fail(client).status_code == 409
    assert fail(client, "CLM-0000").status_code == 404
    start(client)
    decide(client, APPROVE)
    assert fail(client).status_code == 409
    assert status(client) == "in_progress"


def test_a_claim_is_never_decided_or_paid_twice(client):
    start(client)
    decide(client, APPROVE)
    other = {**APPROVE, "payout": "300.00"}
    assert decide(client, other).status_code == 409
    assert client.get("/api/claims/CLM-1001").json()["decision"]["payout"] == "420.00"
    assert pay(client, "420.00").status_code == 200
    assert pay(client, "420.00").status_code == 200
    assert client.get("/api/claims/CLM-1001").json()["payment"]["amount"] == "420.00"
    assert pay(client, "300.00").status_code == 409


def test_reseeding_clears_the_attempts(client):
    start(client)
    fail(client)
    seed()
    start(client)
    assert fail(client).json()["status"] == "waiting"


def test_a_new_run_is_empty_and_unfinished(client):
    assert client.get("/api/runs/current").json() is None
    run = client.post("/api/runs", json={"claim_limit": 5}).json()
    assert run == {
        "run_id": 1,
        "claim_limit": 5,
        "todos": [],
        "summary": None,
        "finished": False,
        "started": [],
    }
    assert client.get("/api/runs/current").json() == run


def test_todos_are_replaced_as_a_whole(client):
    client.post("/api/runs", json={"claim_limit": 5})
    first = [
        {"text": "CLM-1001", "status": "todo"},
        {"text": "CLM-1002", "status": "todo"},
    ]
    assert (
        client.put("/api/runs/1/todos", json={"todos": first}).json()["todos"] == first
    )
    second = [{"text": "CLM-1001", "status": "done"}]
    client.put("/api/runs/1/todos", json={"todos": second})
    assert client.get("/api/runs/current").json()["todos"] == second


@pytest.mark.parametrize("status_", ["todo", "in_progress", "done", "left_for_handler"])
def test_every_todo_status_is_accepted(client, status_):
    client.post("/api/runs", json={"claim_limit": 5})
    todos = {"todos": [{"text": "CLM-1001", "status": status_}]}
    assert client.put("/api/runs/1/todos", json=todos).status_code == 200


def test_bad_run_requests(client):
    client.post("/api/runs", json={"claim_limit": 5})
    bad = {"todos": [{"text": "CLM-1001", "status": "pending"}]}
    assert client.put("/api/runs/1/todos", json=bad).status_code == 422
    assert client.post("/api/runs", json={"claim_limit": 0}).status_code == 422
    assert client.put("/api/runs/9/todos", json={"todos": []}).status_code == 404
    assert (
        client.post("/api/runs/9/finish", json={"summary": "Done"}).status_code == 404
    )


def test_finishing_stores_the_summary_and_the_latest_run_is_current(client):
    client.post("/api/runs", json={"claim_limit": 5})
    finished = client.post("/api/runs/1/finish", json={"summary": "Five decided."})
    assert finished.json()["summary"] == "Five decided."
    assert finished.json()["finished"] is True
    client.post("/api/runs", json={"claim_limit": 2})
    assert client.get("/api/runs/current").json()["run_id"] == 2
    seed()
    assert client.get("/api/runs/current").json() is None


def test_both_sets_of_instructions(client):
    queue = client.get("/api/instructions/queue")
    claim = client.get("/api/instructions/claim")
    assert queue.headers["content-type"].startswith("text/plain")
    assert "queue" in queue.text
    assert "UnderCover Agent" in claim.text


def test_a_run_remembers_the_claims_it_started_once_each(client):
    client.post("/api/runs", json={"claim_limit": 5})
    for claim_id in ["CLM-1003", "CLM-1001", "CLM-1003"]:
        run = client.post("/api/runs/1/claims", json={"claim_id": claim_id}).json()
    assert run["started"] == ["CLM-1003", "CLM-1001"]
    assert client.get("/api/runs/current").json()["started"] == ["CLM-1003", "CLM-1001"]
    missing = client.post("/api/runs/9/claims", json={"claim_id": "CLM-1001"})
    assert missing.status_code == 404
