"""The tables, written once for SQLite and Postgres. Money and records are text."""

from sqlalchemy import (
    Boolean,
    Column,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    false,
)

metadata = MetaData()

claims = Table(
    "claims",
    metadata,
    Column("claim_id", Text, primary_key=True),
    Column("status", Text, nullable=False),
    Column("data", Text, nullable=False),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("thread_id", Text),
)
policies = Table(
    "policies",
    metadata,
    Column("policy_id", Text, primary_key=True),
    Column("data", Text, nullable=False),
)
customers = Table(
    "customers",
    metadata,
    Column("customer_id", Text, primary_key=True),
    Column("data", Text, nullable=False),
)
decisions = Table(
    "decisions",
    metadata,
    Column("claim_id", Text, primary_key=True),
    Column("decision", Text, nullable=False),
    Column("payout", Text, nullable=False),
    Column("explanation", Text, nullable=False),
    Column("policy_section", Text, nullable=False),
)
payments = Table(
    "payments",
    metadata,
    Column("claim_id", Text, primary_key=True),
    Column("amount", Text, nullable=False),
)
steps = Table(
    "steps",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("claim_id", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("text", Text, nullable=False),
)
reads = Table(
    "reads",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("claim_id", Text, nullable=False),
    Column("document", Text, nullable=False),
    Column("section", Text, nullable=False),
    UniqueConstraint("claim_id", "document", "section"),
)
runs = Table(
    "runs",
    metadata,
    Column("run_id", Integer, primary_key=True, autoincrement=True),
    Column("claim_limit", Integer, nullable=False),
    Column("todos", Text, nullable=False),
    Column("summary", Text),
    Column("finished", Boolean, nullable=False, server_default=false()),
)
sign_offs = Table(
    "sign_offs",
    metadata,
    Column("claim_id", Text, primary_key=True),
    Column("handler_id", Text, nullable=False),
    Column("signed_off_by", Text, nullable=False),
    Column("signed_off_at", Text, nullable=False),
)
run_claims = Table(
    "run_claims",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", Integer, nullable=False),
    Column("claim_id", Text, nullable=False),
    UniqueConstraint("run_id", "claim_id"),
)
