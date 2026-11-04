"""The instructions give a goal and limits. They are not a procedure."""

import re
from pathlib import Path

INSTRUCTIONS = Path(__file__).parent.parent / "instructions"
MAX_WORDS = {"claim.md": 400, "queue.md": 250}
NUMBERED = re.compile(r"^\s*\d+[.)]\s", re.MULTILINE)
TOOLS = [
    "get_claim",
    "get_policy",
    "get_customer",
    "get_contents",
    "read_section",
    "record_decision",
    "pay_claim",
    "list_waiting_claims",
    "write_todos",
    "work_claim",
    "finish_run",
]


def text_of(name: str) -> str:
    return (INSTRUCTIONS / name).read_text(encoding="utf-8")


def test_instructions_have_no_numbered_steps():
    assert [n for n in MAX_WORDS if NUMBERED.search(text_of(n))] == []


def test_instructions_do_not_name_tools():
    named = [n for n in MAX_WORDS if any(t in text_of(n) for t in TOOLS)]
    assert named == []


def test_instructions_stay_short():
    long = [n for n, limit in MAX_WORDS.items() if len(text_of(n).split()) > limit]
    assert long == []
