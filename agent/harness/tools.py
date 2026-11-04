"""Tools whose refusals go back to the model as text."""

from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool, tool


def text_tool(function: Callable[..., Any]) -> BaseTool:
    """Make a tool from a function. A ToolException it raises becomes its answer."""
    built = tool(function)
    built.handle_tool_error = True
    return built
