"""The policy wording and the claims manual by section, and the instructions."""

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from backend import store
from backend.documents import sections
from backend.models import SectionRead, SectionRef
from backend.routes.dependencies import Db

router = APIRouter()

INSTRUCTIONS = Path(__file__).parent.parent / "instructions"


def section_of(document: str, number: str) -> tuple[str, str]:
    """Return a section's (title, text), or raise a 404."""
    try:
        return sections(document)[number]
    except KeyError:
        raise HTTPException(404, f"Section {number} of {document} not found") from None


@router.get(
    "/documents/{document}/contents",
    operation_id="get_contents",
    response_class=PlainTextResponse,
)
def get_contents(document: str) -> str:
    """List the numbers and titles of a document's sections."""
    try:
        found = sections(document)
    except KeyError:
        raise HTTPException(404, f"Document {document} not found") from None
    return "\n".join(f"{number}. {title}" for number, (title, _) in found.items())


@router.post(
    "/claims/{claim_id}/reads",
    operation_id="read_section",
    response_class=PlainTextResponse,
)
def read_section(claim_id: str, ref: SectionRef, conn: Db) -> str:
    """Read one section of a document and record the read on the claim."""
    store.claim_row(conn, claim_id)
    _, text = section_of(ref.document, ref.section)
    store.add_read(conn, claim_id, ref)
    return text


@router.get("/claims/{claim_id}/reads", operation_id="list_reads")
def list_reads(claim_id: str, conn: Db) -> list[SectionRead]:
    """List the sections read on a claim, in the order first read."""
    store.claim_row(conn, claim_id)
    return [
        SectionRead(**ref.model_dump(), title=section_of(ref.document, ref.section)[0])
        for ref in store.reads(conn, claim_id)
    ]


@router.get(
    "/instructions/queue",
    operation_id="get_queue_instructions",
    response_class=PlainTextResponse,
)
def get_queue_instructions() -> str:
    """Get the instructions for running the queue."""
    return (INSTRUCTIONS / "queue.md").read_text(encoding="utf-8")


@router.get(
    "/instructions/claim",
    operation_id="get_claim_instructions",
    response_class=PlainTextResponse,
)
def get_claim_instructions() -> str:
    """Get the instructions for working one claim."""
    return (INSTRUCTIONS / "claim.md").read_text(encoding="utf-8")
