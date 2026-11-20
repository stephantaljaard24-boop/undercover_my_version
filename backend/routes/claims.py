"""The claims in the queue, and the steps that take one from waiting to decided."""

import sqlite3

from fastapi import APIRouter

from backend import payout, rules, store
from backend.models import (
    ClaimDetail,
    ClaimSummary,
    Decision,
    Failure,
    Payment,
    PayoutCalculation,
    PayoutRequest,
    Status,
    Step,
)
from backend.routes.dependencies import Db

router = APIRouter()


def move(
    conn: sqlite3.Connection, claim_id: str, source: Status, target: Status
) -> ClaimDetail:
    """Move a claim from one status to another, or raise a 409."""
    rules.require_status(claim_id, store.claim_row(conn, claim_id)["status"], source)
    store.set_status(conn, claim_id, target)
    return store.claim_detail(conn, claim_id)


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
    """Move a waiting claim to in progress."""
    return move(conn, claim_id, "waiting", "in_progress")


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
    """Record the decision on a claim that is in progress."""
    status = store.claim_row(conn, claim_id)["status"]
    rules.require_status(claim_id, status, "in_progress")
    store.add_decision(conn, claim_id, decision, rules.status_after_decision(decision))
    return store.claim_detail(conn, claim_id)


@router.post("/claims/{claim_id}/payment", operation_id="pay_claim")
def pay_claim(claim_id: str, payment: Payment, conn: Db) -> ClaimDetail:
    """Pay the amount of an approved claim's payout, unless it needs sign-off."""
    detail = store.claim_detail(conn, claim_id)
    rules.require_payable(claim_id, detail.decision, detail.payment, payment)
    store.add_payment(conn, claim_id, payment)
    return store.claim_detail(conn, claim_id)


@router.post("/claims/{claim_id}/fail", operation_id="fail_claim")
def fail_claim(claim_id: str, failure: Failure, conn: Db) -> ClaimDetail:
    """Record a failed attempt on a claim in progress and send it back to waiting."""
    row = store.claim_row(conn, claim_id)
    rules.require_status(claim_id, row["status"], "in_progress")
    attempts = row["attempts"] + 1
    status = rules.status_after_failure(attempts)
    store.record_failure(conn, claim_id, attempts, status, failure.reason)
    return store.claim_detail(conn, claim_id)
