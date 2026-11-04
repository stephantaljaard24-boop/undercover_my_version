"""Load the database from data/. Run `uv run -m backend.seed` to reset it."""

import json

from backend.data import load_json
from backend.db import SCHEMA, connect, db_path


def seed() -> None:
    """Replace everything in the database with the starting queue."""
    claims = load_json("claims.json")
    policies = load_json("policies.json")
    customers = load_json("customers.json")
    conn = connect()
    with conn:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO claims (claim_id, status, data) VALUES (?, 'waiting', ?)",
            [(c["claim_id"], json.dumps(c, default=str)) for c in claims],
        )
        conn.executemany(
            "INSERT INTO policies (policy_id, data) VALUES (?, ?)",
            [(p["policy_id"], json.dumps(p, default=str)) for p in policies],
        )
        conn.executemany(
            "INSERT INTO customers (customer_id, data) VALUES (?, ?)",
            [(c["customer_id"], json.dumps(c, default=str)) for c in customers],
        )
    conn.close()
    print(f"Loaded {len(claims)} claims into {db_path()}")


if __name__ == "__main__":
    seed()
