"""The UnderCover backend."""

import json
import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

from backend.db import DATA_DIR, connect, db_path
from backend.documents import sections
from backend.models import (
    Claim,
    ClaimDetail,
    ClaimSummary,
    Customer,
    Decision,
    Payment,
    Policy,
    SectionRead,
    SectionRef,
    Status,
    Step,
)
from backend.seed import seed

INSTRUCTIONS = Path(__file__).parent / "instructions.md"


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


def find(conn: sqlite3.Connection, sql: str, key: str) -> sqlite3.Row:
    """Return the one row the query finds for a key, or raise a 404."""
    row = conn.execute(sql, (key,)).fetchone()
    if row is None:
        raise HTTPException(404, f"{key} not found")
    return row


def decision_of(conn: sqlite3.Connection, claim_id: str) -> Decision | None:
    row = conn.execute(
        "SELECT decision, payout, explanation, policy_section FROM decisions"
        " WHERE claim_id = ?",
        (claim_id,),
    ).fetchone()
    return Decision(**row) if row else None


def payment_of(conn: sqlite3.Connection, claim_id: str) -> Payment | None:
    row = conn.execute(
        "SELECT amount FROM payments WHERE claim_id = ?", (claim_id,)
    ).fetchone()
    return Payment(**row) if row else None


def claim_detail(conn: sqlite3.Connection, claim_id: str) -> ClaimDetail:
    row = find(conn, "SELECT * FROM claims WHERE claim_id = ?", claim_id)
    claim = Claim(**json.loads(row["data"]))
    return ClaimDetail(
        **dict(claim),
        status=row["status"],
        decision=decision_of(conn, claim_id),
        payment=payment_of(conn, claim_id),
    )


def section_of(document: str, number: str) -> tuple[str, str]:
    """Return a section's (title, text), or raise a 404."""
    try:
        return sections(document)[number]
    except KeyError:
        raise HTTPException(404, f"Section {number} of {document} not found") from None


def approval_limit() -> Decimal:
    text = (DATA_DIR / "company.json").read_text(encoding="utf-8")
    return json.loads(text, parse_float=Decimal)["payout_approval_limit"]


def move(
    conn: sqlite3.Connection, claim_id: str, source: Status, target: Status
) -> ClaimDetail:
    """Move a claim from one status to another, or raise a 409."""
    row = find(conn, "SELECT status FROM claims WHERE claim_id = ?", claim_id)
    if row["status"] != source:
        raise HTTPException(409, f"Claim {claim_id} is {row['status']}, not {source}")
    with conn:
        conn.execute(
            "UPDATE claims SET status = ? WHERE claim_id = ?", (target, claim_id)
        )
    return claim_detail(conn, claim_id)


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}


@app.get("/api/claims", operation_id="list_claims")
def list_claims(conn: Db) -> list[ClaimSummary]:
    """List every claim in the queue with its status and decision."""
    names = {
        row["customer_id"]: json.loads(row["data"])["name"]
        for row in conn.execute("SELECT * FROM customers")
    }
    summaries = []
    for row in conn.execute("SELECT claim_id FROM claims ORDER BY claim_id"):
        detail = claim_detail(conn, row["claim_id"])
        summaries.append(
            ClaimSummary(
                claim_id=detail.claim_id,
                customer_name=names[detail.customer_id],
                claim_type=detail.claim_type,
                summary=detail.summary,
                submitted_on=detail.submitted_on,
                amount_claimed=detail.amount_claimed,
                status=detail.status,
                decision=detail.decision.decision if detail.decision else None,
                payout=detail.decision.payout if detail.decision else None,
            )
        )
    return summaries


@app.get("/api/claims/{claim_id}", operation_id="get_claim")
def get_claim(claim_id: str, conn: Db) -> ClaimDetail:
    """Get one claim in full, with its status, decision and payment."""
    return claim_detail(conn, claim_id)


@app.get("/api/policies/{policy_id}", operation_id="get_policy")
def get_policy(policy_id: str, conn: Db) -> Policy:
    """Get a policy with its plan, add-ons, trip and travelers."""
    row = find(conn, "SELECT * FROM policies WHERE policy_id = ?", policy_id)
    return Policy(**json.loads(row["data"]))


@app.get("/api/customers/{customer_id}", operation_id="get_customer")
def get_customer(customer_id: str, conn: Db) -> Customer:
    """Get a customer with their earlier claims."""
    row = find(conn, "SELECT * FROM customers WHERE customer_id = ?", customer_id)
    return Customer(**json.loads(row["data"]))


@app.get(
    "/api/policy-wording",
    operation_id="get_policy_wording",
    response_class=PlainTextResponse,
)
def get_policy_wording() -> str:
    """Get the policy wording."""
    return (DATA_DIR / "policy_wording.md").read_text(encoding="utf-8")


@app.get(
    "/api/instructions",
    operation_id="get_instructions",
    response_class=PlainTextResponse,
)
def get_instructions() -> str:
    """Get the agent's instructions."""
    return INSTRUCTIONS.read_text(encoding="utf-8")


@app.post("/api/claims/{claim_id}/start", operation_id="start_claim")
def start_claim(claim_id: str, conn: Db) -> ClaimDetail:
    """Move a waiting claim to in progress."""
    return move(conn, claim_id, "waiting", "in_progress")


@app.post("/api/claims/{claim_id}/release", operation_id="release_claim")
def release_claim(claim_id: str, conn: Db) -> ClaimDetail:
    """Put a claim that is in progress back to waiting."""
    return move(conn, claim_id, "in_progress", "waiting")


@app.get("/api/claims/{claim_id}/steps", operation_id="list_steps")
def list_steps(claim_id: str, conn: Db) -> list[Step]:
    """List what the agent has done on a claim, oldest first."""
    find(conn, "SELECT claim_id FROM claims WHERE claim_id = ?", claim_id)
    rows = conn.execute(
        "SELECT kind, text FROM steps WHERE claim_id = ? ORDER BY id", (claim_id,)
    )
    return [Step(**row) for row in rows]


@app.post("/api/claims/{claim_id}/steps", operation_id="add_step")
def add_step(claim_id: str, step: Step, conn: Db) -> Step:
    """Record one step the agent took on a claim."""
    find(conn, "SELECT claim_id FROM claims WHERE claim_id = ?", claim_id)
    with conn:
        conn.execute(
            "INSERT INTO steps (claim_id, kind, text) VALUES (?, ?, ?)",
            (claim_id, step.kind, step.text),
        )
    return step


@app.post("/api/claims/{claim_id}/decision", operation_id="record_decision")
def record_decision(claim_id: str, decision: Decision, conn: Db) -> ClaimDetail:
    """Record the decision on a claim that is in progress."""
    row = find(conn, "SELECT status FROM claims WHERE claim_id = ?", claim_id)
    if row["status"] != "in_progress":
        raise HTTPException(
            409, f"Claim {claim_id} is {row['status']}, not in_progress"
        )
    after = "awaiting_sign_off" if decision.payout > approval_limit() else "decided"
    with conn:
        conn.execute(
            "INSERT INTO decisions VALUES (?, ?, ?, ?, ?)",
            (
                claim_id,
                decision.decision,
                str(decision.payout),
                decision.explanation,
                decision.policy_section,
            ),
        )
        conn.execute(
            "UPDATE claims SET status = ? WHERE claim_id = ?", (after, claim_id)
        )
    return claim_detail(conn, claim_id)


@app.post("/api/claims/{claim_id}/payment", operation_id="pay_claim")
def pay_claim(claim_id: str, payment: Payment, conn: Db) -> ClaimDetail:
    """Pay the amount of an approved claim's payout, unless it needs sign-off."""
    detail = claim_detail(conn, claim_id)
    decision = detail.decision
    if decision is None or decision.decision != "approve":
        raise HTTPException(409, f"Claim {claim_id} has no approved payout")
    limit = approval_limit()
    if decision.payout > limit:
        raise HTTPException(
            403, f"A payout over ${limit:,.2f} needs a handler's sign-off."
        )
    if detail.payment:
        raise HTTPException(409, f"Claim {claim_id} is already paid")
    if payment.amount != decision.payout:
        raise HTTPException(409, f"The payout is ${decision.payout:,.2f}")
    with conn:
        conn.execute(
            "INSERT INTO payments VALUES (?, ?)", (claim_id, str(payment.amount))
        )
    return claim_detail(conn, claim_id)


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
    find(conn, "SELECT claim_id FROM claims WHERE claim_id = ?", claim_id)
    _, text = section_of(ref.document, ref.section)
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO reads (claim_id, document, section)"
            " VALUES (?, ?, ?)",
            (claim_id, ref.document, ref.section),
        )
    return text


@app.get("/api/claims/{claim_id}/reads", operation_id="list_reads")
def list_reads(claim_id: str, conn: Db) -> list[SectionRead]:
    """List the sections read on a claim, in the order first read."""
    find(conn, "SELECT claim_id FROM claims WHERE claim_id = ?", claim_id)
    rows = conn.execute(
        "SELECT document, section FROM reads WHERE claim_id = ? ORDER BY id",
        (claim_id,),
    )
    return [
        SectionRead(
            document=row["document"],
            section=row["section"],
            title=section_of(row["document"], row["section"])[0],
        )
        for row in rows
    ]
