"""Running an agent and turning its messages into steps."""

import json
from collections.abc import Callable, Iterator

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from agent.harness import tracing

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
    agent: CompiledStateGraph,
    prompt: str,
    thread_id: str,
    tags: list[str] | None = None,
) -> Iterator[tuple[str, str]]:
    """Run the agent on a prompt and yield each step as it happens.

    With tags, the run is traced in a Langfuse session named for the thread.
    """
    config = tracing.settings(thread_id, tags) if tags is not None else RunnableConfig()
    config["configurable"] = {"thread_id": thread_id}
    chunks = agent.stream(
        {"messages": [{"role": "user", "content": prompt}]},
        config=config,
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
    tags: list[str] | None = None,
) -> str:
    """Run the agent on a prompt, hand each step to on_step, return the last reply."""
    reply = ""
    try:
        for kind, text in stream_steps(agent, prompt, thread_id, tags):
            if on_step:
                on_step(kind, text)
            if kind == "reply":
                reply = text
    finally:
        if tags is not None:
            tracing.flush()
    return reply
