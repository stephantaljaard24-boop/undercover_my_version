"""The to-do list an agent keeps for a long job."""

from collections.abc import Callable
from typing import Literal

from langchain_core.tools import BaseTool
from pydantic import BaseModel

from agent.harness.tools import text_tool

TodoStatus = Literal["todo", "in_progress", "done", "left_for_handler"]


class TodoItem(BaseModel):
    text: str
    status: TodoStatus


def todo_tool(save: Callable[[list[TodoItem]], object]) -> BaseTool:
    """Build the write_todos tool, which hands the whole list to save."""

    @text_tool
    def write_todos(todos: list[TodoItem]) -> str:
        """Replace the run's to-do list. Each item has text and a status of todo,
        in_progress, done or left_for_handler."""
        save(todos)
        return "To-do list saved."

    return write_todos
