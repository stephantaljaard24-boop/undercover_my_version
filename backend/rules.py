"""The rules for moving a claim along: statuses, attempts, sign-off and payment."""

from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException

from backend.data import load_json
from backend.models import ClaimDetail, Decision, Handler, Status

MAX_ATTEMPTS = 2


def approval_limit() -> Decimal:
    """Return the largest payout that is paid without a handler's sign-off."""
    return load_json("company.json")["payout_approval_limit"]


def require_status(claim_id: str, status: str, expected: Status) -> None:
    """Raise a 409 unless the claim has the status the move needs."""
    if status != expected:
        raise HTTPException(409, f"Claim {claim_id} is {status}, not {expected}")


def new_thread_id(claim_id: str) -> str:
    """Name a new thread of work on a claim."""
    return f"{claim_id}-{uuid4().hex[:8]}"


def status_after_decision(decision: Decision) -> Status:
    """A decline or referral is decided. An approval is paid first, and a payout
    over the limit waits for sign-off before that."""
    if decision.decision != "approve":
        return "decided"
    return "awaiting_sign_off" if decision.payout > approval_limit() else "in_progress"


def status_after_failure(attempts: int) -> Status:
    """A claim goes back to waiting, until it has failed too often."""
    return "needs_handler" if attempts >= MAX_ATTEMPTS else "waiting"


def is_repeat_decision(claim: ClaimDetail, decision: Decision) -> bool:
    """True if the claim already has this decision. A different one is a 409."""
    existing = claim.decision
    if existing is None:
        return False
    if (existing.decision, existing.payout) != (decision.decision, decision.payout):
        raise HTTPException(
            409, f"Claim {claim.claim_id} already has a {existing.decision} decision"
        )
    return True


def require_undecided(claim: ClaimDetail) -> None:
    """Raise a 409 for a claim with a decision, which never goes back in the queue."""
    if claim.decision is not None:
        raise HTTPException(
            409, f"Claim {claim.claim_id} has a decision and can't go back in the queue"
        )


def payment_is_due(claim: ClaimDetail, amount: Decimal) -> bool:
    """True if the payment is to be made, and False if it is a repeat.

    Raise unless the amount is the approved payout and the payout is allowed.
    """
    decision = claim.decision
    if decision is None or decision.decision != "approve":
        raise HTTPException(409, f"Claim {claim.claim_id} has no approved payout")
    limit = approval_limit()
    if decision.payout > limit and claim.sign_off is None:
        raise HTTPException(
            403, f"A payout over ${limit:,.2f} needs a handler's sign-off."
        )
    if amount != decision.payout:
        raise HTTPException(409, f"The payout is ${decision.payout:,.2f}")
    return claim.payment is None


def signing_handler(handler_id: str) -> Handler:
    """Return the handler, who must exist and be allowed to sign off a large payout."""
    handlers = {h["handler_id"]: h for h in load_json("handlers.json")}
    if handler_id not in handlers:
        raise HTTPException(404, f"{handler_id} not found")
    handler = Handler(**handlers[handler_id])
    if not handler.can_approve_over_limit:
        raise HTTPException(
            403, f"{handler.name} can't sign off a payout over the limit"
        )
    return handler
