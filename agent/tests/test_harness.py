"""The harness on its own: no claims, no backend."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import ToolException, tool

from agent.harness import agents
from agent.harness.agents import build_agent
from agent.harness.limits import Run
from agent.harness.model import chat_model
from agent.harness.steps import RESULT_LIMIT, run_agent, steps_of
from agent.harness.todos import TodoItem, todo_tool
from agent.harness.tools import text_tool
from agent.tests.stubs import FlakyModel, call, script


@tool
def look(thing: str) -> str:
    """Look at a thing."""
    return f"a {thing}"


def test_an_agent_retries_a_model_that_fails_once():
    llm = FlakyModel(
        messages=iter([call("look", thing="cat"), AIMessage(content="ok")])
    )
    agent = build_agent(llm, [look], "Be brief.")
    assert run_agent(agent, "Look.", "t") == "ok"


def test_an_agent_stops_after_too_many_model_calls(monkeypatch):
    monkeypatch.setattr(agents, "MODEL_CALL_LIMIT", 2)
    llm = script(*[call("look", call_id=str(n), thing="cat") for n in range(5)])
    with pytest.raises(Exception, match="limit"):
        run_agent(build_agent(llm, [look], "Be brief."), "Look.", "t")


def test_the_system_prompt_and_the_call_limit_are_what_it_is_given():
    llm = script(AIMessage(content="ok"))
    run_agent(build_agent(llm, [look], "Be brief.", call_limit=5), "Look.", "t")
    assert llm.seen[0][0].content == "Be brief."
    assert llm.seen[0][1].content == "Look."


def test_steps_of_each_kind_of_message():
    assert steps_of(AIMessage(content="hi")) == [("reply", "hi")]
    asked = call("look", thing="cat")
    assert steps_of(asked) == [("tool_call", 'look {"thing": "cat"}')]
    result = ToolMessage(content="x" * (RESULT_LIMIT + 5), tool_call_id="1")
    assert steps_of(result) == [("tool_result", "x" * RESULT_LIMIT + "...")]
    assert steps_of(HumanMessage(content="hello")) == []


def test_run_agent_reports_steps_in_order_and_returns_the_last_reply():
    llm = script(call("look", thing="cat"), AIMessage(content="A cat."))
    steps = []
    reply = run_agent(
        build_agent(llm, [look], "Be brief."),
        "Look.",
        "t",
        on_step=lambda kind, text: steps.append(kind),
    )
    assert reply == "A cat."
    assert steps == ["tool_call", "tool_result", "reply"]


def test_a_refusal_goes_back_to_the_model_as_text():
    @text_tool
    def refuse() -> str:
        """Always refused."""
        raise ToolException("Not today.")

    assert refuse.invoke({}) == "Not today."


def test_the_to_do_tool_hands_the_whole_list_to_save():
    saved = []
    write = todo_tool(saved.append)
    items = [{"text": "one", "status": "todo"}, {"text": "two", "status": "done"}]
    assert write.invoke({"todos": items}) == "To-do list saved."
    assert saved == [
        [TodoItem(text="one", status="todo"), TodoItem(text="two", status="done")]
    ]


def test_a_status_outside_the_four_is_not_taken():
    write = todo_tool(lambda _: None)
    with pytest.raises(Exception, match="status"):
        write.invoke({"todos": [{"text": "one", "status": "later"}]})


def test_the_run_refuses_items_past_its_cap():
    run = Run(2)
    assert run.admit("a")
    assert run.admit("b")
    assert not run.admit("c")
    assert run.admit("a")


def test_the_run_names_the_items_it_must_still_work():
    run = Run(2)
    run.admit("a")
    assert run.unfinished(["a", "b", "c"]) == ["a", "b", "c"]
    run.admit("b")
    assert run.unfinished(["a", "c"]) == ["a"]
    assert run.unfinished([]) == []


def test_model_name(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    assert chat_model().model_name == "deepseek/deepseek-v4.1-flash"
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    assert chat_model().model_name == "openrouter/free"
