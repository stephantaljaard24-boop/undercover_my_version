"""The queue agent: one run works the whole queue from a to-do list it keeps."""

import threading
from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel

from agent import runner, tools
from agent.main import build_agent, model, stream_steps

QUEUE_CALL_LIMIT = 400


class TodoItem(BaseModel):
    text: str
    status: Literal["todo", "in_progress", "done", "left_for_handler"]


class Run:
    """One run of the queue agent: its cap and the claims it has started."""

    def __init__(self, run_id: int, limit: int, claim_llm: BaseChatModel | None):
        self.run_id = run_id
        self.limit = limit
        self.claim_llm = claim_llm
        self.started: set[str] = set()
        self.summary: str | None = None
        self.lock = threading.Lock()

    def missed(self, claims: list[dict]) -> list[str]:
        """Waiting claims the run must still work: retries, and new ones in the cap."""
        return [
            claim["claim_id"]
            for claim in claims
            if claim["status"] == "waiting"
            and (claim["claim_id"] in self.started or len(self.started) < self.limit)
        ]


def queue_tools(run: Run) -> list[BaseTool]:
    """Build the queue agent's tools for one run."""

    @tool
    def list_waiting_claims() -> str:
        """List the claims that are waiting, one line each."""
        with tools.backend() as client:
            claims = client.get("/api/claims").json()
        lines = [
            f"{c['claim_id']} | {c['claim_type']} | submitted {c['submitted_on']}"
            f" | ${c['amount_claimed']} | {c['summary']}"
            for c in claims
            if c["status"] == "waiting"
        ]
        return "\n".join(lines) or "No claims are waiting."

    @tool
    def write_todos(todos: list[TodoItem]) -> str:
        """Replace the run's to-do list. Each item has text and a status of todo,
        in_progress, done or left_for_handler."""
        body = {"todos": [todo.model_dump() for todo in todos]}
        with tools.backend() as client:
            response = client.put(f"/api/runs/{run.run_id}/todos", json=body)
        if response.is_success:
            return "To-do list saved."
        return tools.reply_of(response)

    @tool
    def work_claim(claim_id: str) -> str:
        """Hand one waiting claim to a fresh helper and get back one line saying
        what happened."""
        with run.lock:
            with tools.backend() as client:
                response = client.get(f"/api/claims/{claim_id}")
            if response.is_error:
                return f"Refused: {claim_id} was not found."
            status = response.json()["status"]
            if status != "waiting":
                return f"Refused: {claim_id} is {status}, not waiting."
            if claim_id not in run.started and len(run.started) >= run.limit:
                return f"Refused: this run's cap of {run.limit} claims is used up."
            run.started.add(claim_id)
            line = runner.work_claim(claim_id, run.claim_llm)
        print(line)
        return line

    @tool
    def finish_run(summary: str) -> str:
        """Finish the run with a short summary for the handlers. It is refused while
        a waiting claim is still within the cap."""
        with tools.backend() as client:
            claims = client.get("/api/claims").json()
            missed = run.missed(claims)
            if missed:
                return (
                    f"Refused: still waiting and within the cap: {', '.join(missed)}."
                    " Work them first."
                )
            client.post(f"/api/runs/{run.run_id}/finish", json={"summary": summary})
        run.summary = summary
        return "Run finished."

    return [list_waiting_claims, write_todos, work_claim, finish_run]


def run_queue(
    limit: int | None = None,
    llm: BaseChatModel | None = None,
    claim_llm: BaseChatModel | None = None,
) -> str:
    """Run the queue agent on the waiting claims, up to a cap; return its summary."""
    with tools.backend() as client:
        instructions = client.get("/api/instructions/queue").text
        waiting = [
            c for c in client.get("/api/claims").json() if c["status"] == "waiting"
        ]
        if not waiting:
            print("No claims are waiting.")
            return ""
        cap = limit or len(waiting)
        run = Run(
            client.post("/api/runs", json={"claim_limit": cap}).json()["run_id"],
            cap,
            claim_llm,
        )
        agent = build_agent(
            llm or model(), queue_tools(run), instructions, QUEUE_CALL_LIMIT
        )
        last_reply = ""
        prompt = f"Work the queue. You may start up to {cap} claims."
        for kind, text in stream_steps(agent, prompt, f"queue-{run.run_id}"):
            if kind == "reply":
                last_reply = text
        if run.summary is None:
            run.summary = last_reply or "The run ended without a summary."
            client.post(f"/api/runs/{run.run_id}/finish", json={"summary": run.summary})
    print(run.summary)
    return run.summary
