"""All the queries: every statement the backend runs is written here, once."""

import json
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import (
    Connection,
    Executable,
    RowMapping,
    Select,
    exists,
    insert,
    literal,
    select,
    update,
)

from backend import schema
from backend.models import (
    Amount,
    Claim,
    ClaimDetail,
    ClaimSummary,
    Customer,
    Decision,
    Handler,
    Payment,
    Policy,
    Run,
    SectionRef,
    SignOff,
    Status,
    Step,
    Todo,
)
from backend.schema import (
    claims,
    customers,
    decisions,
    payments,
    policies,
    run_claims,
    runs,
    sign_offs,
)


def found[Row](row: Row | None, key: object) -> Row:
    """Return the row, or raise a 404 naming the key it was looked up by."""
    if row is None:
        raise HTTPException(404, f"{key} not found")
    return row


def one(conn: Connection, query: Select) -> RowMapping | None:
    return conn.execute(query).mappings().first()


def write(conn: Connection, *statements: Executable) -> None:
    """Run the statements as one transaction."""
    for statement in statements:
        conn.execute(statement)
    conn.commit()


def of_claim(table, claim_id: str) -> Select:
    """Select a claim's one row from a table keyed by claim id."""
    return select(table).where(table.c.claim_id == claim_id)


def claim_status(claim_id: str, **values: object):
    return update(claims).where(claims.c.claim_id == claim_id).values(**values)


def claim_row(conn: Connection, claim_id: str) -> RowMapping:
    """Return a claim's row (status, attempts, thread and data), or raise a 404."""
    return found(one(conn, of_claim(claims, claim_id)), claim_id)


def set_status(conn: Connection, claim_id: str, status: Status) -> None:
    write(conn, claim_status(claim_id, status=status))


def start_claim(conn: Connection, claim_id: str, thread_id: str) -> None:
    """Move the claim to in progress, on a new thread."""
    write(conn, claim_status(claim_id, status="in_progress", thread_id=thread_id))


def claim_detail(conn: Connection, claim_id: str) -> ClaimDetail:
    row = claim_row(conn, claim_id)
    decision = one(conn, of_claim(decisions, claim_id))
    payment = one(conn, of_claim(payments, claim_id))
    signed = one(conn, of_claim(sign_offs, claim_id))
    sign_off = SignOff(**signed) if signed else None
    signer = sign_off.model_dump(exclude={"handler_id"}) if sign_off else {}
    return ClaimDetail(
        **dict(Claim(**json.loads(row["data"]))),
        status=row["status"],
        thread_id=row["thread_id"],
        decision=Decision(**decision) if decision else None,
        sign_off=sign_off,
        payment=Payment(**payment, **signer) if payment else None,
    )


def claim_summaries(conn: Connection) -> list[ClaimSummary]:
    """Every claim in the queue, with its customer's name and its decision."""
    names = {
        row["customer_id"]: json.loads(row["data"])["name"]
        for row in conn.execute(select(customers)).mappings()
    }
    rows = conn.execute(
        select(claims.c.status, claims.c.data, decisions.c.decision, decisions.c.payout)
        .select_from(
            claims.outerjoin(decisions, decisions.c.claim_id == claims.c.claim_id)
        )
        .order_by(claims.c.claim_id)
    ).mappings()
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


def policy(conn: Connection, policy_id: str) -> Policy:
    query = select(policies.c.data).where(policies.c.policy_id == policy_id)
    return Policy(**json.loads(found(conn.execute(query).first(), policy_id)[0]))


def claim_policy(conn: Connection, claim_id: str) -> Policy:
    """The policy a claim is made under."""
    claim = Claim(**json.loads(claim_row(conn, claim_id)["data"]))
    return policy(conn, claim.policy_id)


def customer(conn: Connection, customer_id: str) -> Customer:
    query = select(customers.c.data).where(customers.c.customer_id == customer_id)
    return Customer(**json.loads(found(conn.execute(query).first(), customer_id)[0]))


def steps(conn: Connection, claim_id: str) -> list[Step]:
    """The steps taken on a claim, oldest first."""
    query = of_claim(schema.steps, claim_id).order_by(schema.steps.c.id)
    return [Step(**row) for row in conn.execute(query).mappings()]


def add_step(conn: Connection, claim_id: str, step: Step) -> None:
    write(
        conn,
        insert(schema.steps).values(claim_id=claim_id, **step.model_dump()),
    )


def add_decision(
    conn: Connection, claim_id: str, decision: Decision, status: Status
) -> None:
    """Store a decision and move the claim to the status that follows it."""
    values = {**decision.model_dump(mode="json"), "claim_id": claim_id}
    write(
        conn, insert(decisions).values(**values), claim_status(claim_id, status=status)
    )


def add_payment(conn: Connection, claim_id: str, payment: Amount) -> None:
    """Store a payment, which ends the claim's work."""
    values = {"claim_id": claim_id, "amount": str(payment.amount)}
    write(
        conn,
        insert(payments).values(**values),
        claim_status(claim_id, status="decided"),
    )


def add_sign_off(conn: Connection, claim_id: str, handler: Handler) -> None:
    """Store a handler's sign-off, which puts the claim back in progress."""
    values = {
        "claim_id": claim_id,
        "handler_id": handler.handler_id,
        "signed_off_by": handler.name,
        "signed_off_at": datetime.now(UTC).isoformat(),
    }
    write(
        conn,
        insert(sign_offs).values(**values),
        claim_status(claim_id, status="in_progress"),
    )


def record_failure(
    conn: Connection, claim_id: str, attempts: int, status: Status, reason: str
) -> None:
    """Store a failed attempt: the new status and count, and an error step."""
    error = f"Attempt {attempts} failed: {reason}"
    write(
        conn,
        claim_status(claim_id, status=status, attempts=attempts),
        insert(schema.steps).values(claim_id=claim_id, kind="error", text=error),
    )


def add_read(conn: Connection, claim_id: str, ref: SectionRef) -> None:
    """Record that a section was read on a claim, once."""
    reads = schema.reads
    already = exists().where(
        reads.c.claim_id == claim_id,
        reads.c.document == ref.document,
        reads.c.section == ref.section,
    )
    new = select(literal(claim_id), literal(ref.document), literal(ref.section)).where(
        ~already
    )
    write(conn, insert(reads).from_select(["claim_id", "document", "section"], new))


def reads(conn: Connection, claim_id: str) -> list[SectionRef]:
    """The sections read on a claim, in the order first read."""
    query = of_claim(schema.reads, claim_id).order_by(schema.reads.c.id)
    return [SectionRef(**row) for row in conn.execute(query).mappings()]


def run_of(conn: Connection, row: RowMapping) -> Run:
    started = conn.execute(
        select(run_claims.c.claim_id)
        .where(run_claims.c.run_id == row["run_id"])
        .order_by(run_claims.c.id)
    )
    return Run(
        run_id=row["run_id"],
        claim_limit=row["claim_limit"],
        todos=json.loads(row["todos"]),
        summary=row["summary"],
        finished=row["finished"],
        started=[r[0] for r in started],
    )


def run(conn: Connection, run_id: int) -> Run:
    query = select(runs).where(runs.c.run_id == run_id)
    return run_of(conn, found(one(conn, query), run_id))


def start_run(conn: Connection, claim_limit: int) -> Run:
    insert_run = (
        insert(runs).values(claim_limit=claim_limit, todos="[]").returning(runs)
    )
    row = conn.execute(insert_run).mappings().one()
    conn.commit()
    return run_of(conn, row)


def current_run(conn: Connection) -> Run | None:
    row = one(conn, select(runs).order_by(runs.c.run_id.desc()).limit(1))
    return run_of(conn, row) if row else None


def update_run(conn: Connection, run_id: int, **values: object) -> Run:
    run(conn, run_id)
    write(conn, update(runs).where(runs.c.run_id == run_id).values(**values))
    return run(conn, run_id)


def set_todos(conn: Connection, run_id: int, todos: list[Todo]) -> Run:
    return update_run(
        conn, run_id, todos=json.dumps([todo.model_dump() for todo in todos])
    )


def finish_run(conn: Connection, run_id: int, summary: str) -> Run:
    return update_run(conn, run_id, summary=summary, finished=True)


def add_run_claim(conn: Connection, run_id: int, claim_id: str) -> Run:
    """Record that a run started a claim, once."""
    run(conn, run_id)
    already = exists().where(
        run_claims.c.run_id == run_id, run_claims.c.claim_id == claim_id
    )
    new = select(literal(run_id), literal(claim_id)).where(~already)
    write(conn, insert(run_claims).from_select(["run_id", "claim_id"], new))
    return run(conn, run_id)
