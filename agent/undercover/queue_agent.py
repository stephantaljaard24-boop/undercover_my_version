"""The queue agent: one run works the whole queue from a to-do list it keeps."""

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from agent.harness.agents import build_agent
from agent.harness.limits import Run
from agent.harness.model import chat_model
from agent.harness.steps import run_agent
from agent.harness.todos import todo_tool
from agent.harness.tools import text_tool
from agent.undercover.backend import Backend, Refused, RunState
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
            backend.add_run_claim(run_id, claim_id)
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


def carry_on_stopped(backend: Backend, claims: ClaimAgent) -> None:
    """Carry on every claim a stopped run or a sign-off left in progress."""
    for claim in backend.claims_with("in_progress"):
        print(claims.carry_on(claim.claim_id))


def carry_on_prompt(stopped: RunState) -> str:
    """Tell a new queue agent what the run it carries on has done so far."""
    started = ", ".join(stopped.started) or "none"
    todos = "\n".join(f"- {todo.text}: {todo.status}" for todo in stopped.todos)
    return (
        "Carry on a run that stopped before it finished. You may start up to "
        f"{stopped.claim_limit} claims in all. Already started: {started}.\n"
        f"Your to-do list so far:\n{todos or '- none'}"
    )


def run_queue(
    backend: Backend,
    claims: ClaimAgent,
    limit: int | None = None,
    llm: BaseChatModel | None = None,
) -> str:
    """Carry on what was left, then run the queue agent; return its summary.

    A run that was stopped is carried on with its cap, its to-do list and the
    claims it started. Otherwise a new run starts, capped at the limit.
    """
    carry_on_stopped(backend, claims)
    stopped = backend.current_run()
    if stopped and not stopped.finished:
        run_id, run = stopped.run_id, Run(stopped.claim_limit, stopped.started)
        prompt = carry_on_prompt(stopped)
    else:
        waiting = backend.waiting_claims()
        if not waiting:
            print("No claims are waiting.")
            return ""
        cap = limit or len(waiting)
        run_id, run = backend.start_run(cap), Run(cap)
        prompt = f"Work the queue. You may start up to {cap} claims."
    agent = build_agent(
        llm or chat_model(),
        queue_tools(backend, run_id, run, claims),
        backend.queue_instructions(),
        QUEUE_CALL_LIMIT,
    )
    last_reply = run_agent(agent, prompt, f"queue-{run_id}")
    summary = run.summary or end_run(
        backend, run_id, run, last_reply or "The run ended without a summary."
    )
    print(summary)
    return summary
