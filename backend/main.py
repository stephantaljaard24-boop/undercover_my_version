"""The UnderCover backend."""

import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

from backend import rules, store
from backend.db import connect, db_path
from backend.documents import sections
from backend.models import (
    ClaimDetail,
    ClaimLimit,
    ClaimSummary,
    Customer,
    Decision,
    Failure,
    Payment,
    Policy,
    Run,
    SectionRead,
    SectionRef,
    Status,
    Step,
    Summary,
    TodoList,
)
from backend.seed import seed

INSTRUCTIONS = Path(__file__).parent / "instructions"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if not db_path().exists():
        seed()
    yield


app = FastAPI(title="UnderCover", lifespan=lifespan)


def get_db() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


Db = Annotated[sqlite3.Connection, Depends(get_db)]


def section_of(document: str, number: str) -> tuple[str, str]:
    """Return a section's (title, text), or raise a 404."""
    try:
        return sections(document)[number]
    except KeyError:
        raise HTTPException(404, f"Section {number} of {document} not found") from None


def move(
    conn: sqlite3.Connection, claim_id: str, source: Status, target: Status
) -> ClaimDetail:
    """Move a claim from one status to another, or raise a 409."""
    rules.require_status(claim_id, store.claim_row(conn, claim_id)["status"], source)
    store.set_status(conn, claim_id, target)
    return store.claim_detail(conn, claim_id)


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}


@app.get("/api/claims", operation_id="list_claims")
def list_claims(conn: Db) -> list[ClaimSummary]:
    """List every claim in the queue with its status and decision."""
    return store.claim_summaries(conn)


@app.get("/api/claims/{claim_id}", operation_id="get_claim")
def get_claim(claim_id: str, conn: Db) -> ClaimDetail:
    """Get one claim in full, with its status, decision and payment."""
    return store.claim_detail(conn, claim_id)


@app.get("/api/policies/{policy_id}", operation_id="get_policy")
def get_policy(policy_id: str, conn: Db) -> Policy:
    """Get a policy with its plan, add-ons, trip and travelers."""
    return store.policy(conn, policy_id)


@app.get("/api/customers/{customer_id}", operation_id="get_customer")
def get_customer(customer_id: str, conn: Db) -> Customer:
    """Get a customer with their earlier claims."""
    return store.customer(conn, customer_id)


@app.post("/api/claims/{claim_id}/start", operation_id="start_claim")
def start_claim(claim_id: str, conn: Db) -> ClaimDetail:
    """Move a waiting claim to in progress."""
    return move(conn, claim_id, "waiting", "in_progress")


@app.get("/api/claims/{claim_id}/steps", operation_id="list_steps")
def list_steps(claim_id: str, conn: Db) -> list[Step]:
    """List what the agent has done on a claim, oldest first."""
    store.claim_row(conn, claim_id)
    return store.steps(conn, claim_id)


@app.post("/api/claims/{claim_id}/steps", operation_id="add_step")
def add_step(claim_id: str, step: Step, conn: Db) -> Step:
    """Record one step the agent took on a claim."""
    store.claim_row(conn, claim_id)
    store.add_step(conn, claim_id, step)
    return step


@app.post("/api/claims/{claim_id}/decision", operation_id="record_decision")
def record_decision(claim_id: str, decision: Decision, conn: Db) -> ClaimDetail:
    """Record the decision on a claim that is in progress."""
    status = store.claim_row(conn, claim_id)["status"]
    rules.require_status(claim_id, status, "in_progress")
    store.add_decision(conn, claim_id, decision, rules.status_after_decision(decision))
    return store.claim_detail(conn, claim_id)


@app.post("/api/claims/{claim_id}/payment", operation_id="pay_claim")
def pay_claim(claim_id: str, payment: Payment, conn: Db) -> ClaimDetail:
    """Pay the amount of an approved claim's payout, unless it needs sign-off."""
    detail = store.claim_detail(conn, claim_id)
    rules.require_payable(claim_id, detail.decision, detail.payment, payment)
    store.add_payment(conn, claim_id, payment)
    return store.claim_detail(conn, claim_id)


@app.get(
    "/api/documents/{document}/contents",
    operation_id="get_contents",
    response_class=PlainTextResponse,
)
def get_contents(document: str) -> str:
    """List the numbers and titles of a document's sections."""
    try:
        found = sections(document)
    except KeyError:
        raise HTTPException(404, f"Document {document} not found") from None
    return "\n".join(f"{number}. {title}" for number, (title, _) in found.items())


@app.post(
    "/api/claims/{claim_id}/reads",
    operation_id="read_section",
    response_class=PlainTextResponse,
)
def read_section(claim_id: str, ref: SectionRef, conn: Db) -> str:
    """Read one section of a document and record the read on the claim."""
    store.claim_row(conn, claim_id)
    _, text = section_of(ref.document, ref.section)
    store.add_read(conn, claim_id, ref)
    return text


@app.get("/api/claims/{claim_id}/reads", operation_id="list_reads")
def list_reads(claim_id: str, conn: Db) -> list[SectionRead]:
    """List the sections read on a claim, in the order first read."""
    store.claim_row(conn, claim_id)
    return [
        SectionRead(**ref.model_dump(), title=section_of(ref.document, ref.section)[0])
        for ref in store.reads(conn, claim_id)
    ]


@app.get(
    "/api/instructions/queue",
    operation_id="get_queue_instructions",
    response_class=PlainTextResponse,
)
def get_queue_instructions() -> str:
    """Get the instructions for running the queue."""
    return (INSTRUCTIONS / "queue.md").read_text(encoding="utf-8")


@app.get(
    "/api/instructions/claim",
    operation_id="get_claim_instructions",
    response_class=PlainTextResponse,
)
def get_claim_instructions() -> str:
    """Get the instructions for working one claim."""
    return (INSTRUCTIONS / "claim.md").read_text(encoding="utf-8")


@app.post("/api/claims/{claim_id}/fail", operation_id="fail_claim")
def fail_claim(claim_id: str, failure: Failure, conn: Db) -> ClaimDetail:
    """Record a failed attempt on a claim in progress and send it back to waiting."""
    row = store.claim_row(conn, claim_id)
    rules.require_status(claim_id, row["status"], "in_progress")
    attempts = row["attempts"] + 1
    status = rules.status_after_failure(attempts)
    store.record_failure(conn, claim_id, attempts, status, failure.reason)
    return store.claim_detail(conn, claim_id)


@app.post("/api/runs", operation_id="start_run")
def start_run(limit: ClaimLimit, conn: Db) -> Run:
    """Start a run of the agent on the queue, with a cap on the claims it may start."""
    return store.start_run(conn, limit.claim_limit)


@app.get("/api/runs/current", operation_id="get_current_run")
def get_current_run(conn: Db) -> Run | None:
    """Get the latest run, or nothing if there has been none."""
    return store.current_run(conn)


@app.put("/api/runs/{run_id}/todos", operation_id="set_todos")
def set_todos(run_id: int, todo_list: TodoList, conn: Db) -> Run:
    """Replace the run's to-do list."""
    return store.set_todos(conn, run_id, todo_list.todos)


@app.post("/api/runs/{run_id}/finish", operation_id="finish_run")
def finish_run(run_id: int, summary: Summary, conn: Db) -> Run:
    """Finish the run with a summary for the handlers."""
    return store.finish_run(conn, run_id, summary.summary)
