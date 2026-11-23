"""The backend's layout: where SQL lives, which way imports point, file size."""

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).parent.parent
SOURCES = [p for p in BACKEND.rglob("*.py") if "tests" not in p.parts]
SQL = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE)\b|\b(select|insert|update|delete)\(|\.execute\("
)
HOLDS_SQL = {"store.py", "db.py", "schema.py", "seed.py"}
MAX_LINES = 300
VAGUE_NAMES = {"utils.py", "helpers.py", "runner.py"}


def imports(path: Path) -> set[str]:
    """Return the modules a file imports, as dotted names."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_sql_is_written_only_in_the_store():
    found = {p.name for p in SOURCES if SQL.search(p.read_text(encoding="utf-8"))}
    assert found <= HOLDS_SQL


def test_nothing_imports_the_entry_point():
    assert [p.name for p in SOURCES if "backend.main" in imports(p)] == []


def test_the_store_and_the_rules_do_not_import_the_routes():
    below = [p for p in SOURCES if "routes" not in p.parts and p.name != "main.py"]
    wrong = [
        p.name for p in below if any(i.startswith("backend.routes") for i in imports(p))
    ]
    assert wrong == []


def test_files_are_named_for_their_job_and_stay_small():
    assert [p.name for p in SOURCES if p.name in VAGUE_NAMES] == []
    long = [
        p.name for p in SOURCES if len(p.read_text("utf-8").splitlines()) > MAX_LINES
    ]
    assert long == []


def test_the_agents_address_is_written_only_in_its_client():
    named = [
        p.name
        for p in SOURCES
        if "UNDERCOVER_AGENT" in p.read_text(encoding="utf-8")
        or "/resume" in p.read_text(encoding="utf-8")
    ]
    assert named == ["agent_client.py"]
