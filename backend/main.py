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
from backend.models import (
    Claim,
    ClaimDetail,
    ClaimSummary,
    Customer,
    Decision,
    Payment,
    Policy,
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


def approval_limit() -> Decimal:
    text = (DATA_DIR / "company.json").read_text(encoding="utf-8")
    return json.loads(text, parse_float=Decimal)["payout_approval_limit"]


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
