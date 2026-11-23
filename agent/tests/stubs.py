"""Stand-ins for a chat model, so no test calls a real one."""

import time
from collections.abc import Iterator
from typing import cast
from uuid import uuid4

import httpx
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from agent.undercover.backend import Backend
from backend import rules, store
from backend.db import engine


class StubModel(GenericFakeChatModel):
    """A chat model that gives scripted replies, then fails as a downed model would."""

    seen: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, *args, **kwargs):
        self.seen.append(messages)
        try:
            reply = next(self.messages)
        except StopIteration:
            raise RuntimeError("model is down") from None
        if isinstance(reply, BaseException):
            raise reply
        return ChatResult(generations=[ChatGeneration(message=cast(AIMessage, reply))])


class Killed(BaseException):
    """The process is stopped, as by a crash or Ctrl-C. Nothing catches it."""


class FlakyModel(StubModel):
    """A chat model whose first call fails."""

    failed: bool = False

    def _generate(self, messages, *args, **kwargs):
        if not self.failed:
            self.failed = True
            raise TimeoutError("the provider timed out")
        return super()._generate(messages, *args, **kwargs)


class ByClaimModel(StubModel):
    """A chat model for helpers: each claim has its own script of replies.

    An entry that is an exception is raised, and a claim with no replies left fails.
    It also records how many calls ran at the same time.
    """

    messages: Iterator = Field(default_factory=lambda: iter(()))
    scripts: dict[str, list] = Field(default_factory=dict)
    active: int = 0
    most_active: int = 0

    def _generate(self, messages, *args, **kwargs):
        claim_id = next(m.content for m in messages if m.type == "human")[:-1].split()[
            -1
        ]
        self.active += 1
        self.most_active = max(self.most_active, self.active)
        time.sleep(0.02)
        self.active -= 1
        self.seen.append(messages)
        script_ = self.scripts.get(claim_id)
        if not script_:
            raise RuntimeError("model is down")
        reply = script_.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(generations=[ChatGeneration(message=cast(AIMessage, reply))])


def call(name, call_id=None, **args):
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": call_id or uuid4().hex}],
    )


def decision_call(**changes):
    """The model's decision on a claim, which the graph records."""
    decision = {
        "decision": "approve",
        "payout": "420.00",
        "explanation": "The delay was long enough and the receipts are in order.",
        "policy_section": "3. Trip Delay",
        **changes,
    }
    return call("ClaimDecision", **decision)


COVERED = AIMessage(content="The delay is covered.")


def approval(claim_id="CLM-1001", **changes):
    """What the model says on a claim it approves: a look at it, a reply, a decision."""
    return [call("get_claim", claim_id=claim_id), COVERED, decision_call(**changes)]


def sign_off(claim_id):
    """A handler signs the claim off, which the dashboard does through the backend."""
    with engine().connect() as conn:
        store.add_sign_off(conn, claim_id, rules.signing_handler("HND-01"))


def script(*replies):
    return StubModel(messages=iter(replies))


def backend_over[B: Backend](client, kind: type[B] = Backend) -> B:  # type: ignore[assignment]
    """A Backend that talks through a test client (which stands in for httpx's)."""
    return kind(cast(httpx.Client, client))
