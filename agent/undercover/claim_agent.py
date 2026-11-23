"""Working one claim on its graph, carrying it on after a stop, and putting right
what goes wrong."""

from collections.abc import Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from agent.harness.checkpoints import Checkpoints
from agent.harness.model import chat_model
from agent.harness.steps import run_graph
from agent.undercover.backend import Backend, Claim, Refused
from agent.undercover.claim_graph import build_claim_graph, initial_input


def describe(claim: Claim, problem: str | None) -> str:
    """Say in one line how a claim ended up."""
    if claim.status == "needs_handler":
        return f"failed again ({problem}), left for a handler"
    if claim.status == "waiting":
        return f"failed ({problem}), back in the queue"
    if claim.decision is None:
        return f"in an unexpected state ({claim.status})"
    line = claim.decision.decision
    if line == "approve":
        line += f" ${claim.decision.payout}"
        if claim.status == "awaiting_sign_off":
            line += ", payment waiting for sign-off"
        else:
            line += ", paid" if claim.payment else ", not paid yet"
    if problem:
        line += f" (stopped: {problem}; the next run carries on)"
    return line


class ClaimAgent:
    """Works claims on the backend, saving each claim's progress in the checkpoints."""

    def __init__(
        self,
        backend: Backend,
        checkpoints: Checkpoints,
        llm: BaseChatModel | None = None,
    ):
        self.backend = backend
        self.checkpoints = checkpoints
        self.llm = llm

    def work_claim(self, claim_id: str) -> str:
        """Start a claim on a new thread and work it; say what happened."""
        try:
            claim = self.backend.start_claim(claim_id)
        except Refused as refusal:
            return f"{claim_id}: not started ({refusal.reason})"
        return self.settle(claim_id, lambda: self.drive(claim_id, claim.thread_id))

    def pick_up(self, claim_id: str) -> str:
        """Carry on a claim that is in progress, or else start it."""
        if self.backend.claim(claim_id).status == "in_progress":
            return self.carry_on(claim_id)
        return self.work_claim(claim_id)

    def carry_on(self, claim_id: str, paused_only: bool = False) -> str:
        """Carry on a claim in progress from the last step its thread saved.

        That is not a new attempt. With paused_only it acts only on a claim a
        handler has signed off.
        """
        claim = self.backend.claim(claim_id)
        waiting = paused_only and claim.sign_off is None
        if claim.status != "in_progress" or claim.thread_id is None or waiting:
            return f"{claim_id}: nothing to carry on ({claim.status})"
        thread_id = claim.thread_id
        return self.settle(
            claim_id, lambda: self.drive(claim_id, thread_id, paused_only)
        )

    def drive(self, claim_id: str, thread_id: str, paused_only: bool = False) -> None:
        """Run a claim's graph until it ends or waits for a handler's sign-off.

        A thread with no saved step is started, one that stopped partway is
        carried on, and one that paused is resumed once the backend has the
        sign-off. With paused_only it does nothing else.
        """
        backend = self.backend
        with self.checkpoints() as saver:
            graph = build_claim_graph(
                backend, self.llm or chat_model(), backend.claim_instructions(), saver
            )
            config = RunnableConfig(configurable={"thread_id": thread_id})
            while True:
                state = graph.get_state(config)
                if state.interrupts:
                    signed = backend.claim(claim_id).sign_off
                    if signed is None:
                        return
                    graph_input = Command(resume={"handler": signed.signed_off_by})
                elif paused_only or (state.values and not state.next):
                    return
                elif state.next:
                    graph_input = None
                else:
                    graph_input = initial_input(claim_id)
                outcome = run_graph(
                    graph,
                    graph_input,
                    thread_id,
                    on_step=lambda kind, text: backend.add_step(claim_id, kind, text),
                    tags=[claim_id],
                )
                if not outcome.paused:
                    return

    def settle(self, claim_id: str, work: Callable[[], None]) -> str:
        """Do the work on a claim and return a line saying how it ended.

        A claim with no decision after an error goes back in the queue. One with
        a decision stays in progress on its thread, and the next run carries it on.
        """
        problem = None
        try:
            work()
        except Exception as error:
            problem = f"{type(error).__name__}: {error}"
        claim = self.backend.claim(claim_id)
        if claim.status == "in_progress" and claim.decision is None:
            problem = problem or "the agent ended without a decision"
            claim = self.backend.fail_claim(claim_id, problem)
        return f"{claim_id}: {describe(claim, problem)}"
