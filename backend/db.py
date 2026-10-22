"""The SQLite store."""

import os
import sqlite3
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DEFAULT_DB = Path(__file__).parent / "undercover.db"

SCHEMA = """
DROP TABLE IF EXISTS claims;
DROP TABLE IF EXISTS policies;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS decisions;
DROP TABLE IF EXISTS payments;
DROP TABLE IF EXISTS steps;
CREATE TABLE claims (
    claim_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE policies (policy_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE customers (customer_id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE decisions (
    claim_id TEXT PRIMARY KEY,
    decision TEXT NOT NULL,
    payout TEXT NOT NULL,
    explanation TEXT NOT NULL,
    policy_section TEXT NOT NULL
);
CREATE TABLE payments (claim_id TEXT PRIMARY KEY, amount TEXT NOT NULL);
CREATE TABLE steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    text TEXT NOT NULL
);
"""


def db_path() -> Path:
    """Return the database file, from UNDERCOVER_DB if it is set."""
    return Path(os.getenv("UNDERCOVER_DB") or DEFAULT_DB)


def connect() -> sqlite3.Connection:
    """Open a connection to the database."""
    conn = sqlite3.connect(db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn
