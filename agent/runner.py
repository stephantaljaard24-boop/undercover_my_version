"""Works one claim with a fresh helper, and puts right what goes wrong."""

from uuid import uuid4

from langchain_core.language_models import BaseChatModel

from agent import tools
from agent.main import run


def describe(claim: dict, problem: str | None) -> str:
    """Say in one line how a claim ended up."""
    if claim["status"] == "needs_handler":
        return f"failed again ({problem}), left for a handler"
    if claim["status"] == "waiting":
        return f"failed ({problem}), back in the queue"
    decision = claim["decision"]
    line = decision["decision"]
    if line == "approve":
        line += f" ${decision['payout']}"
        if claim["status"] == "awaiting_sign_off":
            line += ", payment waiting for sign-off"
        else:
            line += ", paid" if claim["payment"] else ", not paid"
    return f"{line} (the agent then failed: {problem})" if problem else line


def work_claim(claim_id: str, llm: BaseChatModel | None = None) -> str:
    """Start a claim, run the agent on it, and return a line saying what happened.

    A claim that fails before it has a decision goes back in the queue, and one that
    fails after being approved but before being paid is paid here.
    """
    with tools.backend() as client:
        started = client.post(f"/api/claims/{claim_id}/start")
        if started.is_error:
            return f"{claim_id}: not started ({started.json()['detail']})"
        problem = None
        try:
            run(claim_id, f"{claim_id}-{uuid4().hex[:8]}", llm)
        except Exception as error:
            problem = f"{type(error).__name__}: {error}"
        claim = client.get(f"/api/claims/{claim_id}").json()
        if claim["status"] == "in_progress":
            problem = problem or "the agent ended without a decision"
            claim = client.post(
                f"/api/claims/{claim_id}/fail", json={"reason": problem}
            ).json()
        elif problem and claim["status"] == "decided" and claim["payment"] is None:
            decision = claim["decision"]
            if decision["decision"] == "approve":
                client.post(
                    f"/api/claims/{claim_id}/payment",
                    json={"amount": decision["payout"]},
                )
                claim = client.get(f"/api/claims/{claim_id}").json()
    return f"{claim_id}: {describe(claim, problem)}"
