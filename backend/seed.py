"""Load the database from data/. Run `uv run -m backend.seed` to reset it."""

import json

from sqlalchemy import insert

from backend import schema
from backend.data import load_json
from backend.db import describe, engine, reset_schema


def rows(key: str, records: list[dict]) -> list[dict]:
    """Each record as a row of its id and its data."""
    return [{key: r[key], "data": json.dumps(r, default=str)} for r in records]


def seed() -> None:
    """Replace everything in the database with the starting queue."""
    claims = rows("claim_id", load_json("claims.json"))
    reset_schema()
    with engine().begin() as conn:
        conn.execute(
            insert(schema.claims), [{**claim, "status": "waiting"} for claim in claims]
        )
        conn.execute(
            insert(schema.policies), rows("policy_id", load_json("policies.json"))
        )
        conn.execute(
            insert(schema.customers), rows("customer_id", load_json("customers.json"))
        )
    print(f"Loaded {len(claims)} claims into {describe()}")


if __name__ == "__main__":
    seed()
