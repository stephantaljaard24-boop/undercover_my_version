"""What a hand-written graph needs in place of an agent's middleware."""

from langgraph.types import RetryPolicy

from agent.harness import agents

MODEL_CALL_LIMIT = 30


class CallLimitExceeded(RuntimeError):
    """A run called the model more times than it may."""


def count_call(calls: int, limit: int | None = None) -> int:
    """Return the count with one more call, or raise if that call is over the limit."""
    limit = limit or MODEL_CALL_LIMIT
    if calls >= limit:
        raise CallLimitExceeded(f"The model was called {limit} times, the most allowed")
    return calls + 1


def retry_policy() -> RetryPolicy:
    """Try a failing node again a few times, as an agent's retry middleware does.

    Hitting the call limit is not retried.
    """
    return RetryPolicy(
        max_attempts=agents.RETRIES + 1,
        initial_interval=agents.RETRY_DELAY,
        retry_on=lambda error: not isinstance(error, CallLimitExceeded),
    )
