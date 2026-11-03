"""The policy wording and the claims manual, split into their numbered sections."""

import re

from backend.db import DATA_DIR

DOCUMENTS = {
    "policy_wording": "policy_wording.md",
    "claims_manual": "claims_manual.md",
}
HEADING = re.compile(r"^## (\d+)\. (.+)$", re.MULTILINE)


def sections(document: str) -> dict[str, tuple[str, str]]:
    """Return a document's sections as number -> (title, text), in order."""
    text = (DATA_DIR / DOCUMENTS[document]).read_text(encoding="utf-8")
    headings = list(HEADING.finditer(text))
    ends = [h.start() for h in headings[1:]] + [len(text)]
    return {
        h.group(1): (h.group(2), text[h.start() : end].strip())
        for h, end in zip(headings, ends, strict=True)
    }
