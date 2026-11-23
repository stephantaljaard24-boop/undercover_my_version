from typing import cast

from langgraph.graph.state import CompiledStateGraph

from agent.harness import steps, tracing


class FakeHandler:
    """Stands in for Langfuse's callback handler, which would reach the network."""


class FakeAgent:
    """Keeps the config it was run with."""

    def __init__(self):
        self.config: dict = {}

    checkpointer = None

    def stream(self, _input, config, stream_mode, durability):
        self.config = config
        return iter(())


def as_graph(agent: FakeAgent) -> CompiledStateGraph:
    return cast(CompiledStateGraph, agent)


def set_keys(monkeypatch):
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public")
    monkeypatch.setattr(tracing, "CallbackHandler", FakeHandler)


def test_a_run_is_traced_in_a_session_named_for_its_thread(monkeypatch):
    set_keys(monkeypatch)
    config = dict(tracing.settings("CLM-1001-ab12cd34", ["CLM-1001"]))
    assert config["metadata"] == {
        "langfuse_session_id": "CLM-1001-ab12cd34",
        "langfuse_tags": ["CLM-1001"],
    }
    assert [type(c) for c in cast(list, config["callbacks"])] == [FakeHandler]


def test_nothing_is_traced_without_the_keys(monkeypatch):
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    assert tracing.settings("CLM-1001-ab12cd34", ["CLM-1001"]) == {}
    tracing.flush()


def test_run_agent_passes_the_trace_settings_and_flushes(monkeypatch):
    set_keys(monkeypatch)
    flushed = []
    monkeypatch.setattr(tracing, "flush", lambda: flushed.append(True))
    agent = FakeAgent()
    steps.run_agent(
        as_graph(agent),
        "Decide claim CLM-1001.",
        "CLM-1001-ab12cd34",
        None,
        ["CLM-1001"],
    )
    assert agent.config["configurable"] == {"thread_id": "CLM-1001-ab12cd34"}
    assert agent.config["metadata"]["langfuse_session_id"] == "CLM-1001-ab12cd34"
    assert flushed == [True]


def test_an_untagged_run_is_not_traced(monkeypatch):
    set_keys(monkeypatch)
    agent = FakeAgent()
    steps.run_agent(as_graph(agent), "Work the queue.", "queue-1")
    assert agent.config == {"configurable": {"thread_id": "queue-1"}}
