"""The agent's runs on the queue, each with a cap and a to-do list."""

from fastapi import APIRouter

from backend import store
from backend.models import ClaimLimit, Run, RunClaim, Summary, TodoList
from backend.routes.dependencies import Db

router = APIRouter()


@router.post("/runs", operation_id="start_run")
def start_run(limit: ClaimLimit, conn: Db) -> Run:
    """Start a run of the agent on the queue, with a cap on the claims it may start."""
    return store.start_run(conn, limit.claim_limit)


@router.get("/runs/current", operation_id="get_current_run")
def get_current_run(conn: Db) -> Run | None:
    """Get the latest run, or nothing if there has been none."""
    return store.current_run(conn)


@router.put("/runs/{run_id}/todos", operation_id="set_todos")
def set_todos(run_id: int, todo_list: TodoList, conn: Db) -> Run:
    """Replace the run's to-do list."""
    return store.set_todos(conn, run_id, todo_list.todos)


@router.post("/runs/{run_id}/finish", operation_id="finish_run")
def finish_run(run_id: int, summary: Summary, conn: Db) -> Run:
    """Finish the run with a summary for the handlers."""
    return store.finish_run(conn, run_id, summary.summary)


@router.post("/runs/{run_id}/claims", operation_id="add_run_claim")
def add_run_claim(run_id: int, claim: RunClaim, conn: Db) -> Run:
    """Record that the run has started a claim."""
    return store.add_run_claim(conn, run_id, claim.claim_id)
