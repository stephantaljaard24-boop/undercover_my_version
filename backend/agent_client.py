"""Telling the agent's service that a claim was signed off."""

import logging
import os

import httpx

DEFAULT_AGENT = "http://127.0.0.1:8002"
TIMEOUT = 5

logger = logging.getLogger(__name__)


def notify_signed_off(claim_id: str) -> None:
    """Ask the agent's service to carry on with a signed-off claim.

    The sign-off is already saved, so an agent that can't be reached is only logged.
    """
    url = os.getenv("UNDERCOVER_AGENT") or DEFAULT_AGENT
    try:
        httpx.post(f"{url}/api/claims/{claim_id}/resume", timeout=TIMEOUT)
    except httpx.HTTPError as error:
        logger.warning("Could not tell the agent about %s: %s", claim_id, error)
