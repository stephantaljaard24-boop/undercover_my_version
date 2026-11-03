"""Load the database from data/. Run `uv run -m backend.seed` to reset it."""

import json
from decimal import Decimal
from typing import Any

from backend.db import DATA_DIR, SCHEMA, connect, db_path


def load_json(name: str) -> Any:
    """Read a data file, keeping amounts as Decimal."""
    text = (DATA_DIR / name).read_text(encoding="utf-8")
    return json.loads(text, parse_float=Decimal)


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
            "INSERT INTO policies VALUES (?, ?)",
            [(p["policy_id"], json.dumps(p, default=str)) for p in policies],
        )
        conn.executemany(
            "INSERT INTO customers VALUES (?, ?)",
            [(c["customer_id"], json.dumps(c, default=str)) for c in customers],
        )
    conn.close()
    print(f"Loaded {len(claims)} claims into {db_path()}")


if __name__ == "__main__":
    seed()
