"""Building an agent that survives a failing model or tool."""

from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolRetryMiddleware,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph

RETRIES = 2
RETRY_DELAY = 1.0
MODEL_CALL_LIMIT = 40


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
