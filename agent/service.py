"""The agent's service: the backend tells it when a handler has signed off a claim."""

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel

from agent.undercover.backend import Backend
from agent.undercover.checkpoints import claim_checkpoints
from agent.undercover.claim_agent import ClaimAgent

logger = logging.getLogger("uvicorn.error")
one_at_a_time = threading.Lock()


class Accepted(BaseModel):
    claim_id: str


@contextmanager
def open_claims() -> Iterator[ClaimAgent]:
    """The claim agent on the real backend and the real database."""
    with Backend.connect() as backend:
        yield ClaimAgent(backend, claim_checkpoints)


def carry_on(claim_id: str) -> None:
    """Carry on a signed-off claim, one at a time, and log how it went."""
    with one_at_a_time, open_claims() as claims:
        logger.info(claims.carry_on(claim_id, paused_only=True))


app = FastAPI(title="UnderCover Agent")


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the agent's service is running."""
    return {"status": "ok"}


@app.post("/api/claims/{claim_id}/resume", operation_id="resume_claim", status_code=202)
def resume_claim(claim_id: str, tasks: BackgroundTasks) -> Accepted:
    """Carry on a claim a handler has signed off, once the answer is sent."""
    tasks.add_task(carry_on, claim_id)
    return Accepted(claim_id=claim_id)
