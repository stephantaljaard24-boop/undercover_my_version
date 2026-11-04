import re
from pathlib import Path

BACKEND = Path(__file__).parent.parent
SOURCES = [p for p in BACKEND.rglob("*.py") if "tests" not in p.parts]
SQL = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE)\b|\.execute\(")
HOLDS_SQL = {"store.py", "db.py", "seed.py"}


def test_sql_is_written_only_in_the_store():
    found = {p.name for p in SOURCES if SQL.search(p.read_text(encoding="utf-8"))}
    assert found <= HOLDS_SQL
