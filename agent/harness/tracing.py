"""Tracing a run in Langfuse, one session for each thread."""

import os
from typing import Any

from langchain_core.runnables import RunnableConfig
from langfuse import get_client
from langfuse.langchain import CallbackHandler


def enabled() -> bool:
    """True when the Langfuse keys are in the environment."""
    return bool(os.getenv("LANGFUSE_SECRET_KEY") and os.getenv("LANGFUSE_PUBLIC_KEY"))


def session_metadata(session_id: str, tags: list[str]) -> dict[str, Any]:
    """The run metadata Langfuse reads its session and tags from."""
    return {"langfuse_session_id": session_id, "langfuse_tags": tags}


def settings(session_id: str, tags: list[str]) -> RunnableConfig:
    """The run config that traces a run in a session, or nothing without the keys."""
    if not enabled():
        return {}
    return {
        "callbacks": [CallbackHandler()],
        "metadata": session_metadata(session_id, tags),
    }


def flush() -> None:
    """Send what is waiting to Langfuse, before a short-lived process ends."""
    if enabled():
        get_client().flush()
