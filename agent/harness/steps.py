"""Running an agent or a graph and turning its messages into steps."""

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from agent.harness import tracing

RESULT_LIMIT = 400
PAUSED = "paused"


@dataclass
class Outcome:
    """How a run ended: its last reply, and whether it is waiting to be resumed."""

    reply: str
    paused: bool


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
    graph: CompiledStateGraph,
    graph_input: Any,
    thread_id: str,
    tags: list[str] | None = None,
) -> Iterator[tuple[str, str]]:
    """Run the graph and yield each step as it happens, then PAUSED if it paused.

    The input is what to start a thread with, a Command to resume it, or None to
    carry on from the last saved step. With tags, the run is traced in a Langfuse
    session named for the thread.
    """
    config = tracing.settings(thread_id, tags) if tags is not None else RunnableConfig()
    config["configurable"] = {"thread_id": thread_id}
    durability = "sync" if graph.checkpointer else None
    chunks = graph.stream(
        graph_input, config=config, stream_mode="updates", durability=durability
    )
    for chunk in chunks:
        for node, update in chunk.items():
            if node == "__interrupt__":
                yield PAUSED, ""
                continue
            for message in (update or {}).get("messages", []):
                yield from steps_of(message)


def run_graph(
    graph: CompiledStateGraph,
    graph_input: Any,
    thread_id: str,
    on_step: Callable[[str, str], object] | None = None,
    tags: list[str] | None = None,
) -> Outcome:
    """Run a graph, hand each step to on_step, and say how the run ended."""
    outcome = Outcome(reply="", paused=False)
    try:
        for kind, text in stream_steps(graph, graph_input, thread_id, tags):
            if kind == PAUSED:
                outcome.paused = True
                continue
            if on_step:
                on_step(kind, text)
            if kind == "reply":
                outcome.reply = text
    finally:
        if tags is not None:
            tracing.flush()
    return outcome


def run_agent(
    agent: CompiledStateGraph,
    prompt: str,
    thread_id: str,
    on_step: Callable[[str, str], object] | None = None,
    tags: list[str] | None = None,
) -> str:
    """Run an agent on a prompt, hand each step to on_step, return the last reply."""
    graph_input = {"messages": [{"role": "user", "content": prompt}]}
    return run_graph(agent, graph_input, thread_id, on_step, tags).reply
