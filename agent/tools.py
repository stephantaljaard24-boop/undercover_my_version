"""The agent's tools. Each one calls a single backend operation."""

import httpx
from langchain_core.tools import tool

BACKEND_URL = "http://localhost:8000"


def backend() -> httpx.Client:
    """Return a client for the UnderCover backend."""
    return httpx.Client(base_url=BACKEND_URL, timeout=10)


def reply_of(response: httpx.Response) -> str:
    """Return the backend's answer, or its reason if it refused the request."""
    if response.is_client_error:
        return f"Refused ({response.status_code}): {response.text}"
    response.raise_for_status()
    return response.text


def fetch(path: str) -> str:
    with backend() as client:
        return reply_of(client.get(path))


@tool
def get_claim(claim_id: str) -> str:
    """Get a claim in full: the story, the items claimed and the documents."""
    return fetch(f"/api/claims/{claim_id}")


@tool
def get_policy(policy_id: str) -> str:
    """Get a policy: the plan, add-ons, trip dates, trip cost and travelers."""
    return fetch(f"/api/policies/{policy_id}")


@tool
def get_customer(customer_id: str) -> str:
    """Get a customer and their earlier claims."""
    return fetch(f"/api/customers/{customer_id}")


@tool
def get_policy_wording() -> str:
    """Get the policy wording, which every decision follows."""
    return fetch("/api/policy-wording")


@tool
def record_decision(
    claim_id: str,
    decision: str,
    payout: str,
    explanation: str,
    policy_section: str,
) -> str:
    """Record the decision (approve, decline or refer) with the payout as a dollar
    amount such as "420.00" (use "0.00" unless approving), a two or three sentence
    explanation, and the policy section it relies on."""
    body = {
        "decision": decision,
        "payout": payout,
        "explanation": explanation,
        "policy_section": policy_section,
    }
    with backend() as client:
        response = client.post(f"/api/claims/{claim_id}/decision", json=body)
    if response.is_success:
        return f"Decision recorded. The claim is now {response.json()['status']}."
    return reply_of(response)


@tool
def pay_claim(claim_id: str, amount: str) -> str:
    """Pay an approved claim its payout, as a dollar amount such as "420.00"."""
    with backend() as client:
        response = client.post(
            f"/api/claims/{claim_id}/payment", json={"amount": amount}
        )
    if response.is_success:
        return "Payment recorded."
    return reply_of(response)


TOOLS = [
    get_claim,
    get_policy,
    get_customer,
    get_policy_wording,
    record_decision,
    pay_claim,
]
