"""Works through the claims queue, one claim at a time."""

from uuid import uuid4

from langchain_core.language_models import BaseChatModel

from agent import tools
from agent.main import run


def describe(claim: dict) -> str:
    """Say in one line how a claim ended up."""
    decision = claim["decision"]
    if decision is None:
        return "no decision, back in the queue"
    if decision["decision"] != "approve":
        return decision["decision"]
    line = f"approve ${decision['payout']}"
    if claim["status"] == "awaiting_sign_off":
        return f"{line}, payment waiting for sign-off"
    return f"{line}, paid" if claim["payment"] else f"{line}, not paid"


def work_claim(claim_id: str, llm: BaseChatModel | None = None) -> str:
    """Start a claim, run the agent on it, and return a line saying what happened."""
    with tools.backend() as client:
        client.post(f"/api/claims/{claim_id}/start").raise_for_status()
    try:
        run(claim_id, f"{claim_id}-{uuid4().hex[:8]}", llm)
    finally:
        with tools.backend() as client:
            claim = client.get(f"/api/claims/{claim_id}").json()
            if claim["status"] == "in_progress":
                client.post(f"/api/claims/{claim_id}/release")
    with tools.backend() as client:
        claim = client.get(f"/api/claims/{claim_id}").json()
    return f"{claim_id}: {describe(claim)}"


def work_queue(llm: BaseChatModel | None = None) -> list[str]:
    """Work every claim that is waiting, one at a time, printing a line for each."""
    with tools.backend() as client:
        claims = client.get("/api/claims").json()
    lines = []
    for claim in claims:
        if claim["status"] == "waiting":
            lines.append(work_claim(claim["claim_id"], llm))
            print(lines[-1])
    return lines


def main(argv: list[str]) -> None:
    """Work the claim named on the command line, or else the whole queue."""
    if argv:
        print(work_claim(argv[0]))
    else:
        work_queue()
