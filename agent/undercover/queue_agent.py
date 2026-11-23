"""The queue agent: one run works the whole queue from a to-do list it keeps."""

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from agent.harness.agents import build_agent
from agent.harness.limits import Run
from agent.harness.model import chat_model
from agent.harness.steps import run_agent
from agent.harness.todos import todo_tool
from agent.harness.tools import text_tool
from agent.undercover.backend import Backend, Refused
from agent.undercover.claim_agent import ClaimAgent

QUEUE_CALL_LIMIT = 400


def end_run(backend: Backend, run_id: int, run: Run, summary: str) -> str:
    """Finish the run with a summary for the handlers, and return the summary."""
    backend.finish_run(run_id, summary)
    run.summary = summary
    return summary


def queue_tools(
    backend: Backend, run_id: int, run: Run, claims: ClaimAgent
) -> list[BaseTool]:
    """Build the queue agent's tools for one run."""

    @text_tool
    def list_waiting_claims() -> str:
        """List the claims that are waiting, one line each."""
        lines = [
            f"{c.claim_id} | {c.claim_type} | submitted {c.submitted_on}"
            f" | ${c.amount_claimed} | {c.summary}"
            for c in backend.waiting_claims()
        ]
        return "\n".join(lines) or "No claims are waiting."

    @text_tool
    def work_claim(claim_id: str) -> str:
        """Hand one waiting claim to a fresh helper and get back one line saying
        what happened."""
        with run.lock:
            try:
                status = backend.claim(claim_id).status
            except Refused:
                return f"Refused: {claim_id} was not found."
            if status != "waiting":
                return f"Refused: {claim_id} is {status}, not waiting."
            if not run.admit(claim_id):
                return f"Refused: this run's cap of {run.limit} claims is used up."
            line = claims.work_claim(claim_id)
        print(line)
        return line

    @text_tool
    def finish_run(summary: str) -> str:
        """Finish the run with a short summary for the handlers. It is refused while
        a waiting claim is still within the cap."""
        missed = run.unfinished(c.claim_id for c in backend.waiting_claims())
        if missed:
            return (
                f"Refused: still waiting and within the cap: {', '.join(missed)}."
                " Work them first."
            )
        end_run(backend, run_id, run, summary)
        return "Run finished."

    write_todos = todo_tool(lambda todos: backend.set_todos(run_id, todos))
    return [list_waiting_claims, write_todos, work_claim, finish_run]


def run_queue(
    backend: Backend,
    claims: ClaimAgent,
    limit: int | None = None,
    llm: BaseChatModel | None = None,
) -> str:
    """Run the queue agent on the waiting claims, up to a cap; return its summary."""
    waiting = backend.waiting_claims()
    if not waiting:
        print("No claims are waiting.")
        return ""
    cap = limit or len(waiting)
    run_id = backend.start_run(cap)
    run = Run(cap)
    agent = build_agent(
        llm or chat_model(),
        queue_tools(backend, run_id, run, claims),
        backend.queue_instructions(),
        QUEUE_CALL_LIMIT,
    )
    last_reply = run_agent(
        agent, f"Work the queue. You may start up to {cap} claims.", f"queue-{run_id}"
    )
    summary = run.summary or end_run(
        backend, run_id, run, last_reply or "The run ended without a summary."
    )
    print(summary)
    return summary
