"""The rules for moving a claim along: statuses, attempts, sign-off and payment."""

from decimal import Decimal

from fastapi import HTTPException

from backend.data import load_json
from backend.models import Decision, Payment, Status

MAX_ATTEMPTS = 2


def approval_limit() -> Decimal:
    """Return the largest payout that is paid without a handler's sign-off."""
    return load_json("company.json")["payout_approval_limit"]


def require_status(claim_id: str, status: str, expected: Status) -> None:
    """Raise a 409 unless the claim has the status the move needs."""
    if status != expected:
        raise HTTPException(409, f"Claim {claim_id} is {status}, not {expected}")


def status_after_decision(decision: Decision) -> Status:
    """A payout over the limit waits for sign-off."""
    return "awaiting_sign_off" if decision.payout > approval_limit() else "decided"


def status_after_failure(attempts: int) -> Status:
    """A claim goes back to waiting, until it has failed too often."""
    return "needs_handler" if attempts >= MAX_ATTEMPTS else "waiting"


def require_payable(
    claim_id: str, decision: Decision | None, paid: Payment | None, payment: Payment
) -> None:
    """Raise unless the payment is the approved payout, allowed and not yet made."""
    if decision is None or decision.decision != "approve":
        raise HTTPException(409, f"Claim {claim_id} has no approved payout")
    limit = approval_limit()
    if decision.payout > limit:
        raise HTTPException(
            403, f"A payout over ${limit:,.2f} needs a handler's sign-off."
        )
    if paid:
        raise HTTPException(409, f"Claim {claim_id} is already paid")
    if payment.amount != decision.payout:
        raise HTTPException(409, f"The payout is ${decision.payout:,.2f}")
