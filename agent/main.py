"""The UnderCover Agent."""

import json
import os
from collections.abc import Iterator
from typing import Any

from dotenv import load_dotenv
from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolRetryMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph
from pydantic import SecretStr

from agent import tools

load_dotenv(override=True)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
RESULT_LIMIT = 400
RETRIES = 2
RETRY_DELAY = 1.0
MODEL_CALL_LIMIT = 40


def model() -> ChatOpenAI:
    """Return the model named in MODEL_NAME, or DeepSeek V4.1 Flash by default."""
    name = os.getenv("MODEL_NAME")
    return ChatOpenAI(
        model=name or DEFAULT_MODEL,
        base_url=OPENROUTER_BASE_URL,
        api_key=SecretStr(os.environ["OPENROUTER_API_KEY"]),
        reasoning_effort=None if name else "low",
    )


def build_agent(
    llm: BaseChatModel,
    agent_tools: list[BaseTool],
    instructions: str,
    call_limit: int | None = None,
) -> CompiledStateGraph:
    """Build an agent that retries a failing model or tool and stops a runaway loop."""
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        ModelRetryMiddleware(
            max_retries=RETRIES, initial_delay=RETRY_DELAY, on_failure="error"
        ),
        ToolRetryMiddleware(max_retries=RETRIES, initial_delay=RETRY_DELAY),
        ModelCallLimitMiddleware(
            run_limit=call_limit or MODEL_CALL_LIMIT, exit_behavior="error"
        ),
    ]
    return create_agent(
        llm, tools=agent_tools, system_prompt=instructions, middleware=middleware
    )


def steps_of(message: BaseMessage) -> list[tuple[str, str]]:
    """Turn a message into the steps the dashboard shows, as (kind, text)."""
    if isinstance(message, ToolMessage):
        text = message.text
        if len(text) > RESULT_LIMIT:
            text = text[:RESULT_LIMIT] + "..."
        return [("tool_result", text)]
    if isinstance(message, AIMessage):
        if message.tool_calls:
            return [
                ("tool_call", f"{call['name']} {json.dumps(call['args'])}")
                for call in message.tool_calls
            ]
        return [("reply", message.text)]
    return []


def stream_steps(
    agent: CompiledStateGraph, prompt: str, thread_id: str
) -> Iterator[tuple[str, str]]:
    """Run the agent on a prompt and yield each step as it happens."""
    chunks = agent.stream(
        {"messages": [{"role": "user", "content": prompt}]},
        config={"configurable": {"thread_id": thread_id}},
        stream_mode="updates",
    )
    for chunk in chunks:
        for update in chunk.values():
            for message in (update or {}).get("messages", []):
                yield from steps_of(message)


def run(claim_id: str, thread_id: str, llm: BaseChatModel | None = None) -> str:
    """Run the agent on one claim, recording each step, and return its final reply."""
    reply = ""
    with tools.backend() as client:
        instructions = client.get("/api/instructions/claim").text
        agent = build_agent(llm or model(), tools.TOOLS, instructions)
        for kind, text in stream_steps(agent, f"Decide claim {claim_id}.", thread_id):
            client.post(
                f"/api/claims/{claim_id}/steps", json={"kind": kind, "text": text}
            )
            if kind == "reply":
                reply = text
    return reply
