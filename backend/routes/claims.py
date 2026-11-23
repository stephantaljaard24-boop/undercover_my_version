"""The claims in the queue, and the steps that take one from waiting to decided."""

from fastapi import APIRouter, BackgroundTasks

from backend import agent_client, payout, rules, store
from backend.models import (
    Amount,
    ClaimDetail,
    ClaimSummary,
    Decision,
    Failure,
    HandlerChoice,
    PayoutCalculation,
    PayoutRequest,
    Step,
)
from backend.routes.dependencies import Db

router = APIRouter()


@router.get("/claims", operation_id="list_claims")
def list_claims(conn: Db) -> list[ClaimSummary]:
    """List every claim in the queue with its status and decision."""
    return store.claim_summaries(conn)


@router.get("/claims/{claim_id}", operation_id="get_claim")
def get_claim(claim_id: str, conn: Db) -> ClaimDetail:
    """Get one claim in full, with its status, decision and payment."""
    return store.claim_detail(conn, claim_id)


@router.post("/claims/{claim_id}/start", operation_id="start_claim")
def start_claim(claim_id: str, conn: Db) -> ClaimDetail:
    """Move a waiting claim to in progress, on a new thread of work."""
    status = store.claim_row(conn, claim_id)["status"]
    rules.require_status(claim_id, status, "waiting")
    store.start_claim(conn, claim_id, rules.new_thread_id(claim_id))
    return store.claim_detail(conn, claim_id)


@router.get("/claims/{claim_id}/steps", operation_id="list_steps")
def list_steps(claim_id: str, conn: Db) -> list[Step]:
    """List what the agent has done on a claim, oldest first."""
    store.claim_row(conn, claim_id)
    return store.steps(conn, claim_id)


@router.post("/claims/{claim_id}/steps", operation_id="add_step")
def add_step(claim_id: str, step: Step, conn: Db) -> Step:
    """Record one step the agent took on a claim."""
    store.claim_row(conn, claim_id)
    store.add_step(conn, claim_id, step)
    return step


@router.post("/claims/{claim_id}/payout-calculation", operation_id="calculate_payout")
def calculate_payout(
    claim_id: str, request: PayoutRequest, conn: Db
) -> PayoutCalculation:
    """Work out the payout on an approved claim with UnderCover's payout rules."""
    return payout.work_out_payout(
        store.claim_policy(conn, claim_id),
        request.benefit,
        request.lines,
        request.paid_by_others,
    )


@router.post("/claims/{claim_id}/decision", operation_id="record_decision")
def record_decision(claim_id: str, decision: Decision, conn: Db) -> ClaimDetail:
    """Record the decision on a claim in progress, or accept the same one again."""
    claim = store.claim_detail(conn, claim_id)
    if not rules.is_repeat_decision(claim, decision):
        rules.require_status(claim_id, claim.status, "in_progress")
        status = rules.status_after_decision(decision)
        store.add_decision(conn, claim_id, decision, status)
    return store.claim_detail(conn, claim_id)


@router.post("/claims/{claim_id}/sign-off", operation_id="sign_off_claim")
def sign_off_claim(
    claim_id: str, choice: HandlerChoice, tasks: BackgroundTasks, conn: Db
) -> ClaimDetail:
    """Sign off a payout that is waiting for a handler, and tell the agent."""
    claim = store.claim_detail(conn, claim_id)
    if claim.sign_off is not None:
        return claim
    handler = rules.signing_handler(choice.handler_id)
    rules.require_status(claim_id, claim.status, "awaiting_sign_off")
    store.add_sign_off(conn, claim_id, handler)
    tasks.add_task(agent_client.notify_signed_off, claim_id)
    return store.claim_detail(conn, claim_id)


@router.post("/claims/{claim_id}/payment", operation_id="pay_claim")
def pay_claim(claim_id: str, payment: Amount, conn: Db) -> ClaimDetail:
    """Pay an approved claim its payout, unless it needs a sign-off it lacks."""
    claim = store.claim_detail(conn, claim_id)
    if rules.payment_is_due(claim, payment.amount):
        store.add_payment(conn, claim_id, payment)
    return store.claim_detail(conn, claim_id)


@router.post("/claims/{claim_id}/fail", operation_id="fail_claim")
def fail_claim(claim_id: str, failure: Failure, conn: Db) -> ClaimDetail:
    """Record a failed attempt on a claim in progress and send it back to waiting."""
    claim = store.claim_detail(conn, claim_id)
    rules.require_status(claim_id, claim.status, "in_progress")
    rules.require_undecided(claim)
    attempts = store.claim_row(conn, claim_id)["attempts"] + 1
    status = rules.status_after_failure(attempts)
    store.record_failure(conn, claim_id, attempts, status, failure.reason)
    return store.claim_detail(conn, claim_id)
