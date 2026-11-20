"""All the SQL: every statement the backend runs is written here."""

import json
import sqlite3

from fastapi import HTTPException

from backend.models import (
    Claim,
    ClaimDetail,
    ClaimSummary,
    Customer,
    Decision,
    Payment,
    Policy,
    Run,
    SectionRef,
    Status,
    Step,
    Todo,
)


def found(row: sqlite3.Row | None, key: object) -> sqlite3.Row:
    """Return the row, or raise a 404 naming the key it was looked up by."""
    if row is None:
        raise HTTPException(404, f"{key} not found")
    return row


def claim_row(conn: sqlite3.Connection, claim_id: str) -> sqlite3.Row:
    """Return a claim's row (status, attempts and data), or raise a 404."""
    row = conn.execute("SELECT * FROM claims WHERE claim_id = ?", (claim_id,))
    return found(row.fetchone(), claim_id)


def set_status(conn: sqlite3.Connection, claim_id: str, status: Status) -> None:
    with conn:
        conn.execute(
            "UPDATE claims SET status = ? WHERE claim_id = ?", (status, claim_id)
        )


def claim_detail(conn: sqlite3.Connection, claim_id: str) -> ClaimDetail:
    row = claim_row(conn, claim_id)
    decision = conn.execute(
        "SELECT decision, payout, explanation, policy_section FROM decisions"
        " WHERE claim_id = ?",
        (claim_id,),
    ).fetchone()
    payment = conn.execute(
        "SELECT amount FROM payments WHERE claim_id = ?", (claim_id,)
    ).fetchone()
    return ClaimDetail(
        **dict(Claim(**json.loads(row["data"]))),
        status=row["status"],
        decision=Decision(**decision) if decision else None,
        payment=Payment(**payment) if payment else None,
    )


def claim_summaries(conn: sqlite3.Connection) -> list[ClaimSummary]:
    """Every claim in the queue, with its customer's name and its decision."""
    names = {
        row["customer_id"]: json.loads(row["data"])["name"]
        for row in conn.execute("SELECT customer_id, data FROM customers")
    }
    rows = conn.execute(
        "SELECT claims.status, claims.data, decisions.decision, decisions.payout"
        " FROM claims LEFT JOIN decisions ON decisions.claim_id = claims.claim_id"
        " ORDER BY claims.claim_id"
    )
    summaries = []
    for row in rows:
        claim = Claim(**json.loads(row["data"]))
        summaries.append(
            ClaimSummary(
                **claim.model_dump(include=set(ClaimSummary.model_fields)),
                customer_name=names[claim.customer_id],
                status=row["status"],
                decision=row["decision"],
                payout=row["payout"],
            )
        )
    return summaries


def policy(conn: sqlite3.Connection, policy_id: str) -> Policy:
    row = conn.execute("SELECT data FROM policies WHERE policy_id = ?", (policy_id,))
    return Policy(**json.loads(found(row.fetchone(), policy_id)["data"]))


def claim_policy(conn: sqlite3.Connection, claim_id: str) -> Policy:
    """The policy a claim is made under."""
    claim = Claim(**json.loads(claim_row(conn, claim_id)["data"]))
    return policy(conn, claim.policy_id)


def customer(conn: sqlite3.Connection, customer_id: str) -> Customer:
    row = conn.execute(
        "SELECT data FROM customers WHERE customer_id = ?", (customer_id,)
    )
    return Customer(**json.loads(found(row.fetchone(), customer_id)["data"]))


def steps(conn: sqlite3.Connection, claim_id: str) -> list[Step]:
    """The steps taken on a claim, oldest first."""
    rows = conn.execute(
        "SELECT kind, text FROM steps WHERE claim_id = ? ORDER BY id", (claim_id,)
    )
    return [Step(**row) for row in rows]


def add_step(conn: sqlite3.Connection, claim_id: str, step: Step) -> None:
    with conn:
        conn.execute(
            "INSERT INTO steps (claim_id, kind, text) VALUES (?, ?, ?)",
            (claim_id, step.kind, step.text),
        )


def add_decision(
    conn: sqlite3.Connection, claim_id: str, decision: Decision, status: Status
) -> None:
    """Store a decision and move the claim to the status that follows it."""
    with conn:
        conn.execute(
            "INSERT INTO decisions"
            " (claim_id, decision, payout, explanation, policy_section)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                claim_id,
                decision.decision,
                str(decision.payout),
                decision.explanation,
                decision.policy_section,
            ),
        )
        conn.execute(
            "UPDATE claims SET status = ? WHERE claim_id = ?", (status, claim_id)
        )


def add_payment(conn: sqlite3.Connection, claim_id: str, payment: Payment) -> None:
    with conn:
        conn.execute(
            "INSERT INTO payments (claim_id, amount) VALUES (?, ?)",
            (claim_id, str(payment.amount)),
        )


def record_failure(
    conn: sqlite3.Connection,
    claim_id: str,
    attempts: int,
    status: Status,
    reason: str,
) -> None:
    """Store a failed attempt: the new status and count, and an error step."""
    with conn:
        conn.execute(
            "UPDATE claims SET status = ?, attempts = ? WHERE claim_id = ?",
            (status, attempts, claim_id),
        )
        conn.execute(
            "INSERT INTO steps (claim_id, kind, text) VALUES (?, 'error', ?)",
            (claim_id, f"Attempt {attempts} failed: {reason}"),
        )


def add_read(conn: sqlite3.Connection, claim_id: str, ref: SectionRef) -> None:
    """Record that a section was read on a claim, once."""
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO reads (claim_id, document, section)"
            " VALUES (?, ?, ?)",
            (claim_id, ref.document, ref.section),
        )


def reads(conn: sqlite3.Connection, claim_id: str) -> list[SectionRef]:
    """The sections read on a claim, in the order first read."""
    rows = conn.execute(
        "SELECT document, section FROM reads WHERE claim_id = ? ORDER BY id",
        (claim_id,),
    )
    return [SectionRef(**row) for row in rows]


def run_of(row: sqlite3.Row) -> Run:
    return Run(
        run_id=row["run_id"],
        claim_limit=row["claim_limit"],
        todos=json.loads(row["todos"]),
        summary=row["summary"],
        finished=bool(row["finished"]),
    )


def run(conn: sqlite3.Connection, run_id: int) -> Run:
    row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,))
    return run_of(found(row.fetchone(), run_id))


def start_run(conn: sqlite3.Connection, claim_limit: int) -> Run:
    with conn:
        row = conn.execute(
            "INSERT INTO runs (claim_limit, todos) VALUES (?, '[]') RETURNING *",
            (claim_limit,),
        ).fetchone()
    return run_of(row)


def current_run(conn: sqlite3.Connection) -> Run | None:
    row = conn.execute("SELECT * FROM runs ORDER BY run_id DESC LIMIT 1").fetchone()
    return run_of(row) if row else None


def set_todos(conn: sqlite3.Connection, run_id: int, todos: list[Todo]) -> Run:
    run(conn, run_id)
    with conn:
        conn.execute(
            "UPDATE runs SET todos = ? WHERE run_id = ?",
            (json.dumps([todo.model_dump() for todo in todos]), run_id),
        )
    return run(conn, run_id)


def finish_run(conn: sqlite3.Connection, run_id: int, summary: str) -> Run:
    run(conn, run_id)
    with conn:
        conn.execute(
            "UPDATE runs SET summary = ?, finished = 1 WHERE run_id = ?",
            (summary, run_id),
        )
    return run(conn, run_id)
