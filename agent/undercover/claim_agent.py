"""Working one claim with a fresh helper, and putting right what goes wrong."""

from uuid import uuid4

from langchain_core.language_models import BaseChatModel

from agent.harness.agents import build_agent
from agent.harness.model import chat_model
from agent.harness.steps import run_agent
from agent.undercover.backend import Backend, Claim, Refused
from agent.undercover.tools import claim_tools


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
            line += ", paid" if claim.payment else ", not paid"
    return f"{line} (the agent then failed: {problem})" if problem else line


def run_helper(
    backend: Backend, claim_id: str, thread_id: str, llm: BaseChatModel | None
) -> str:
    """Run the helper on one claim, recording each step on it, and return its reply."""
    agent = build_agent(
        llm or chat_model(), claim_tools(backend), backend.claim_instructions()
    )
    return run_agent(
        agent,
        f"Decide claim {claim_id}.",
        thread_id,
        on_step=lambda kind, text: backend.add_step(claim_id, kind, text),
    )


def work_claim(
    backend: Backend, claim_id: str, llm: BaseChatModel | None = None
) -> str:
    """Start a claim, run the helper on it, and return a line saying what happened.

    A claim that fails before it has a decision goes back in the queue, and one that
    fails after being approved but before being paid is paid here.
    """
    try:
        backend.start_claim(claim_id)
    except Refused as refusal:
        return f"{claim_id}: not started ({refusal.reason})"
    problem = None
    try:
        run_helper(backend, claim_id, f"{claim_id}-{uuid4().hex[:8]}", llm)
    except Exception as error:
        problem = f"{type(error).__name__}: {error}"
    claim = backend.claim(claim_id)
    if claim.status == "in_progress":
        problem = problem or "the agent ended without a decision"
        claim = backend.fail_claim(claim_id, problem)
    elif problem and claim.status == "decided" and claim.payment is None:
        if claim.decision and claim.decision.decision == "approve":
            claim = backend.pay(claim_id, claim.decision.payout)
    return f"{claim_id}: {describe(claim, problem)}"
