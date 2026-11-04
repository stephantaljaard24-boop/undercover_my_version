"""Running an agent and turning its messages into steps."""

import json
from collections.abc import Callable, Iterator

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph

RESULT_LIMIT = 400


def steps_of(message: BaseMessage) -> list[tuple[str, str]]:
    """Turn a message into steps, as (kind, text)."""
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


def run_agent(
    agent: CompiledStateGraph,
    prompt: str,
    thread_id: str,
    on_step: Callable[[str, str], object] | None = None,
) -> str:
    """Run the agent on a prompt, hand each step to on_step, return the last reply."""
    reply = ""
    for kind, text in stream_steps(agent, prompt, thread_id):
        if on_step:
            on_step(kind, text)
        if kind == "reply":
            reply = text
    return reply
