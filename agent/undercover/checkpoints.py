"""Where the claim graph saves its progress: the undercover schema of DATABASE_URL."""

import os
from contextlib import AbstractContextManager

from langgraph.checkpoint.base import BaseCheckpointSaver

from agent.harness.checkpoints import postgres_checkpoints

SCHEMA = "undercover"


def claim_checkpoints() -> AbstractContextManager[BaseCheckpointSaver]:
    """Open the saver for the claim graph on the database in DATABASE_URL."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set. The agent saves its progress there.")
    return postgres_checkpoints(url, SCHEMA)
