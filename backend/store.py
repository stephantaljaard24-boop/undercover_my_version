"""All the queries: every statement the backend runs is written here, once."""

import json

from fastapi import HTTPException
from sqlalchemy import Connection, RowMapping, exists, insert, literal, select, update

from backend import schema
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


def found[Row](row: Row | None, key: object) -> Row:
    """Return the row, or raise a 404 naming the key it was looked up by."""
    if row is None:
        raise HTTPException(404, f"{key} not found")
    return row


def claim_row(conn: Connection, claim_id: str) -> RowMapping:
    """Return a claim's row (status, attempts and data), or raise a 404."""
    query = select(schema.claims).where(schema.claims.c.claim_id == claim_id)
    return found(conn.execute(query).mappings().first(), claim_id)


def set_status(conn: Connection, claim_id: str, status: Status) -> None:
    conn.execute(
        update(schema.claims)
        .where(schema.claims.c.claim_id == claim_id)
        .values(status=status)
    )
    conn.commit()


def claim_detail(conn: Connection, claim_id: str) -> ClaimDetail:
    row = claim_row(conn, claim_id)
    decided = schema.decisions
    decision = (
        conn.execute(
            select(
                decided.c.decision,
                decided.c.payout,
                decided.c.explanation,
                decided.c.policy_section,
            ).where(decided.c.claim_id == claim_id)
        )
        .mappings()
        .first()
    )
    payment = (
        conn.execute(
            select(schema.payments.c.amount).where(
                schema.payments.c.claim_id == claim_id
            )
        )
        .mappings()
        .first()
    )
    return ClaimDetail(
        **dict(Claim(**json.loads(row["data"]))),
        status=row["status"],
        decision=Decision(**decision) if decision else None,
        payment=Payment(**payment) if payment else None,
    )


def claim_summaries(conn: Connection) -> list[ClaimSummary]:
    """Every claim in the queue, with its customer's name and its decision."""
    names = {
        row["customer_id"]: json.loads(row["data"])["name"]
        for row in conn.execute(
            select(schema.customers.c.customer_id, schema.customers.c.data)
        ).mappings()
    }
    claims, decisions = schema.claims, schema.decisions
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
    query = select(schema.policies.c.data).where(
        schema.policies.c.policy_id == policy_id
    )
    return Policy(**json.loads(found(conn.execute(query).first(), policy_id)[0]))


def claim_policy(conn: Connection, claim_id: str) -> Policy:
    """The policy a claim is made under."""
    claim = Claim(**json.loads(claim_row(conn, claim_id)["data"]))
    return policy(conn, claim.policy_id)


def customer(conn: Connection, customer_id: str) -> Customer:
    query = select(schema.customers.c.data).where(
        schema.customers.c.customer_id == customer_id
    )
    return Customer(**json.loads(found(conn.execute(query).first(), customer_id)[0]))


def steps(conn: Connection, claim_id: str) -> list[Step]:
    """The steps taken on a claim, oldest first."""
    rows = conn.execute(
        select(schema.steps.c.kind, schema.steps.c.text)
        .where(schema.steps.c.claim_id == claim_id)
        .order_by(schema.steps.c.id)
    ).mappings()
    return [Step(**row) for row in rows]


def add_step(conn: Connection, claim_id: str, step: Step) -> None:
    conn.execute(
        insert(schema.steps).values(claim_id=claim_id, kind=step.kind, text=step.text)
    )
    conn.commit()


def add_decision(
    conn: Connection, claim_id: str, decision: Decision, status: Status
) -> None:
    """Store a decision and move the claim to the status that follows it."""
    conn.execute(
        insert(schema.decisions).values(
            claim_id=claim_id,
            decision=decision.decision,
            payout=str(decision.payout),
            explanation=decision.explanation,
            policy_section=decision.policy_section,
        )
    )
    conn.execute(
        update(schema.claims)
        .where(schema.claims.c.claim_id == claim_id)
        .values(status=status)
    )
    conn.commit()


def add_payment(conn: Connection, claim_id: str, payment: Payment) -> None:
    conn.execute(
        insert(schema.payments).values(claim_id=claim_id, amount=str(payment.amount))
    )
    conn.commit()


def record_failure(
    conn: Connection, claim_id: str, attempts: int, status: Status, reason: str
) -> None:
    """Store a failed attempt: the new status and count, and an error step."""
    conn.execute(
        update(schema.claims)
        .where(schema.claims.c.claim_id == claim_id)
        .values(status=status, attempts=attempts)
    )
    conn.execute(
        insert(schema.steps).values(
            claim_id=claim_id,
            kind="error",
            text=f"Attempt {attempts} failed: {reason}",
        )
    )
    conn.commit()


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
    conn.execute(insert(reads).from_select(["claim_id", "document", "section"], new))
    conn.commit()


def reads(conn: Connection, claim_id: str) -> list[SectionRef]:
    """The sections read on a claim, in the order first read."""
    rows = conn.execute(
        select(schema.reads.c.document, schema.reads.c.section)
        .where(schema.reads.c.claim_id == claim_id)
        .order_by(schema.reads.c.id)
    ).mappings()
    return [SectionRef(**row) for row in rows]


def run_of(row: RowMapping) -> Run:
    return Run(
        run_id=row["run_id"],
        claim_limit=row["claim_limit"],
        todos=json.loads(row["todos"]),
        summary=row["summary"],
        finished=row["finished"],
    )


def run(conn: Connection, run_id: int) -> Run:
    query = select(schema.runs).where(schema.runs.c.run_id == run_id)
    return run_of(found(conn.execute(query).mappings().first(), run_id))


def start_run(conn: Connection, claim_limit: int) -> Run:
    row = (
        conn.execute(
            insert(schema.runs)
            .values(claim_limit=claim_limit, todos="[]")
            .returning(schema.runs)
        )
        .mappings()
        .one()
    )
    conn.commit()
    return run_of(row)


def current_run(conn: Connection) -> Run | None:
    row = (
        conn.execute(select(schema.runs).order_by(schema.runs.c.run_id.desc()).limit(1))
        .mappings()
        .first()
    )
    return run_of(row) if row else None


def set_todos(conn: Connection, run_id: int, todos: list[Todo]) -> Run:
    run(conn, run_id)
    conn.execute(
        update(schema.runs)
        .where(schema.runs.c.run_id == run_id)
        .values(todos=json.dumps([todo.model_dump() for todo in todos]))
    )
    conn.commit()
    return run(conn, run_id)


def finish_run(conn: Connection, run_id: int, summary: str) -> Run:
    run(conn, run_id)
    conn.execute(
        update(schema.runs)
        .where(schema.runs.c.run_id == run_id)
        .values(summary=summary, finished=True)
    )
    conn.commit()
    return run(conn, run_id)
