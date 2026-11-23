"""The agent's layout: what imports what, where the backend is named, file size."""

import ast
import re
from pathlib import Path

AGENT = Path(__file__).parent.parent
FILES = [p for p in AGENT.rglob("*.py") if p.name != "test_layout.py"]
SOURCES = [p for p in FILES if "tests" not in p.parts]
HARNESS = [p for p in SOURCES if "harness" in p.parts]
UNDERCOVER = [p for p in SOURCES if "undercover" in p.parts]
MAX_LINES = 300
BACKEND_PATH = re.compile(
    r"/api/(claims|policies|customers|documents|instructions|runs)"
)
VAGUE_NAMES = {"main.py", "utils.py", "helpers.py", "runner.py"}
ENTRY_POINTS = ("agent.__main__", "agent.service")
SERVICE_PATHS = {"/api/health", "/api/claims/{claim_id}/resume"}


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


def importing(files: list[Path], *prefixes: str) -> list[str]:
    """The files that import any module that is, or is inside, one of the prefixes."""
    return [
        p.name
        for p in files
        if any(i == x or i.startswith(f"{x}.") for i in imports(p) for x in prefixes)
    ]


def test_the_harness_imports_nothing_from_the_product():
    wrong = importing(HARNESS, "agent.undercover", *ENTRY_POINTS, "backend")
    assert wrong == []


def test_the_product_imports_neither_an_entry_point_nor_the_backend_server():
    assert importing(UNDERCOVER, *ENTRY_POINTS, "backend") == []


def test_nothing_imports_an_entry_point():
    assert importing(SOURCES, *ENTRY_POINTS) == []


def test_files_are_named_for_their_job_and_stay_small():
    assert [p.name for p in SOURCES if p.name in VAGUE_NAMES] == []
    long = [
        p.name for p in SOURCES if len(p.read_text("utf-8").splitlines()) > MAX_LINES
    ]
    assert long == []


def test_the_backend_is_named_only_in_its_client():
    named = [
        p.name for p in FILES if BACKEND_PATH.search(p.read_text(encoding="utf-8"))
    ]
    assert sorted(named) == ["backend.py", "service.py"]
    uses_httpx = [p.name for p in FILES if "httpx" in p.read_text(encoding="utf-8")]
    assert sorted(uses_httpx) == ["backend.py", "stubs.py"]


def test_the_service_names_only_its_own_paths():
    text = (AGENT / "service.py").read_text(encoding="utf-8")
    assert set(re.findall(r'"(/api/[^"]*)"', text)) == SERVICE_PATHS
