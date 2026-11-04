"""The UnderCover backend as the agent sees it. Only this module knows its address."""

import os
from types import TracebackType
from typing import Self

import httpx
from langchain_core.tools import ToolException
from pydantic import BaseModel

from agent.harness.todos import TodoItem


class Refused(ToolException):
    """The backend turned a request down, and said why."""

    def __init__(self, status_code: int, reason: str):
        super().__init__(f"Refused ({status_code}): {reason}")
        self.status_code = status_code
        self.reason = reason


class Decision(BaseModel):
    decision: str
    payout: str


class Payment(BaseModel):
    amount: str


class Claim(BaseModel):
    """A claim as the agent works it: where it stands, and what has happened."""

    claim_id: str
    status: str
    decision: Decision | None = None
    payment: Payment | None = None


class QueuedClaim(BaseModel):
    """A claim in the queue, as one line."""

    claim_id: str
    claim_type: str
    submitted_on: str
    amount_claimed: str
    summary: str
    status: str


class Backend:
    """Asks the UnderCover backend for what the agent needs, in the product's terms."""

    def __init__(self, client: httpx.Client):
        self.client = client

    @classmethod
    def connect(cls) -> Self:
        """Connect to the backend at BACKEND_URL, or on this machine at port 8000."""
        url = os.getenv("BACKEND_URL", "http://localhost:8000")
        return cls(httpx.Client(base_url=url, timeout=10))

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        trace: TracebackType | None,
    ) -> None:
        self.client.close()

    def _send(self, method: str, path: str, body: object = None) -> httpx.Response:
        """Send a request. A refusal raises Refused and any other failure raises."""
        response = self.client.request(method, path, json=body)
        if response.is_client_error:
            detail = response.json().get("detail", response.text)
            raise Refused(response.status_code, str(detail))
        response.raise_for_status()
        return response

    def claim(self, claim_id: str) -> Claim:
        return Claim.model_validate_json(self.claim_text(claim_id))

    def claim_text(self, claim_id: str) -> str:
        """The claim in full, as the backend sends it."""
        return self._send("GET", f"/api/claims/{claim_id}").text

    def waiting_claims(self) -> list[QueuedClaim]:
        claims = self._send("GET", "/api/claims").json()
        return [
            QueuedClaim(**claim) for claim in claims if claim["status"] == "waiting"
        ]

    def policy_text(self, policy_id: str) -> str:
        return self._send("GET", f"/api/policies/{policy_id}").text

    def customer_text(self, customer_id: str) -> str:
        return self._send("GET", f"/api/customers/{customer_id}").text

    def contents(self, document: str) -> str:
        """The numbered sections of the policy wording or the claims manual."""
        return self._send("GET", f"/api/documents/{document}/contents").text

    def read_section(self, claim_id: str, document: str, section: str) -> str:
        """One section of a document, which the backend records as read on the claim."""
        body = {"document": document, "section": section}
        return self._send("POST", f"/api/claims/{claim_id}/reads", body).text

    def start_claim(self, claim_id: str) -> Claim:
        return Claim(**self._send("POST", f"/api/claims/{claim_id}/start").json())

    def fail_claim(self, claim_id: str, reason: str) -> Claim:
        body = {"reason": reason}
        return Claim(**self._send("POST", f"/api/claims/{claim_id}/fail", body).json())

    def record_decision(
        self,
        claim_id: str,
        decision: str,
        payout: str,
        explanation: str,
        policy_section: str,
    ) -> Claim:
        body = {
            "decision": decision,
            "payout": payout,
            "explanation": explanation,
            "policy_section": policy_section,
        }
        response = self._send("POST", f"/api/claims/{claim_id}/decision", body)
        return Claim(**response.json())

    def pay(self, claim_id: str, amount: str) -> Claim:
        body = {"amount": amount}
        return Claim(
            **self._send("POST", f"/api/claims/{claim_id}/payment", body).json()
        )

    def add_step(self, claim_id: str, kind: str, text: str) -> None:
        self._send(
            "POST", f"/api/claims/{claim_id}/steps", {"kind": kind, "text": text}
        )

    def claim_instructions(self) -> str:
        return self._send("GET", "/api/instructions/claim").text

    def queue_instructions(self) -> str:
        return self._send("GET", "/api/instructions/queue").text

    def start_run(self, claim_limit: int) -> int:
        """Start a run with a cap on its claims, and return its id."""
        body = {"claim_limit": claim_limit}
        return self._send("POST", "/api/runs", body).json()["run_id"]

    def set_todos(self, run_id: int, todos: list[TodoItem]) -> None:
        body = {"todos": [todo.model_dump() for todo in todos]}
        self._send("PUT", f"/api/runs/{run_id}/todos", body)

    def finish_run(self, run_id: int, summary: str) -> None:
        self._send("POST", f"/api/runs/{run_id}/finish", {"summary": summary})
