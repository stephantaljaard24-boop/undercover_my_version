"""The policies and customers behind the claims."""

from fastapi import APIRouter

from backend import store
from backend.data import load_json
from backend.models import Customer, Handler, Policy
from backend.routes.dependencies import Db

router = APIRouter()


@router.get("/policies/{policy_id}", operation_id="get_policy")
def get_policy(policy_id: str, conn: Db) -> Policy:
    """Get a policy with its plan, add-ons, trip and travelers."""
    return store.policy(conn, policy_id)


@router.get("/customers/{customer_id}", operation_id="get_customer")
def get_customer(customer_id: str, conn: Db) -> Customer:
    """Get a customer with their earlier claims."""
    return store.customer(conn, customer_id)


@router.get("/handlers", operation_id="list_handlers")
def list_handlers() -> list[Handler]:
    """List the handlers, who may sign off a payout over the limit."""
    return [Handler(**handler) for handler in load_json("handlers.json")]
