"""The UnderCover backend as the agent sees it. Only this module knows its address."""

import os
from types import TracebackType
from typing import Literal, Self

import httpx
from langchain_core.tools import ToolException
from pydantic import BaseModel, Field

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


class SignOff(BaseModel):
    signed_off_by: str


class Claim(BaseModel):
    """A claim as the agent works it: where it stands, and what has happened."""

    claim_id: str
    status: str
    thread_id: str | None = None
    decision: Decision | None = None
    sign_off: SignOff | None = None
    payment: Payment | None = None


class StartedClaim(BaseModel):
    """A claim that has just been started, with the thread its work is saved on."""

    claim_id: str
    thread_id: str


Benefit = Literal[
    "trip_cancellation",
    "trip_interruption",
    "trip_delay",
    "baggage_delay",
    "baggage",
    "passport",
    "emergency_medical",
]


class PayoutLine(BaseModel):
    """One covered item or expense on a claim."""

    description: str = Field(description="What the item or expense is")
    amount: str = Field(
        description="The total claimed for the line in US dollars before any limits, "
        'such as "245.00". For several items, the total for all of them'
    )
    quantity: int = Field(
        description="How many separate items the line holds, such as 3 for three "
        "shirts. A pair or a set is one item. Use 1 when it does not apply"
    )
    kind: Literal[
        "item", "electronics", "cash", "expense", "hotel", "meals_without_receipts"
    ] = Field(
        description="item: a belonging, or a pair or set that counts as one item. "
        "electronics: only a phone, tablet, laptop, camera or its lens, e-reader or "
        "smartwatch; any other device is an item. cash: cash that was lost or stolen. "
        "expense: any other cost with a receipt, such as a medical bill, a meal, a "
        "taxi, a fee or a prepaid trip cost. hotel: a hotel during a trip delay. "
        "meals_without_receipts: meals during a trip delay with no receipts"
    )
    nights: int = Field(description="For a hotel, the number of nights, else 0")
    hours: str = Field(
        description="For meals without receipts, the length of the delay in hours, "
        'such as "30", else "0"'
    )


class CalculationStep(BaseModel):
    step: str
    amount: str


class PayoutCalculation(BaseModel):
    """The payout the rules give, and the calculation behind it."""

    calculation: list[CalculationStep]
    payout: str
    needs_sign_off: bool


class QueuedClaim(BaseModel):
    """A claim in the queue, as one line."""

    claim_id: str
    claim_type: str
    submitted_on: str
    amount_claimed: str
    summary: str
    status: str


class RunState(BaseModel):
    """A run of the queue agent: its cap, its to-do list and what it has started."""

    run_id: int
    claim_limit: int
    finished: bool
    todos: list[TodoItem]
    started: list[str]


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

    def claims_with(self, status: str) -> list[QueuedClaim]:
        """The claims in the queue that have this status."""
        claims = self._send("GET", "/api/claims").json()
        return [QueuedClaim(**claim) for claim in claims if claim["status"] == status]

    def waiting_claims(self) -> list[QueuedClaim]:
        return self.claims_with("waiting")

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

    def start_claim(self, claim_id: str) -> StartedClaim:
        response = self._send("POST", f"/api/claims/{claim_id}/start")
        return StartedClaim(**response.json())

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

    def calculate_payout(
        self,
        claim_id: str,
        benefit: Benefit,
        lines: list[PayoutLine],
        paid_by_others: str,
    ) -> PayoutCalculation:
        """Work out the payout on an approved claim with the backend's payout rules."""
        body = {
            "benefit": benefit,
            "lines": [line.model_dump() for line in lines],
            "paid_by_others": paid_by_others,
        }
        response = self._send(
            "POST", f"/api/claims/{claim_id}/payout-calculation", body
        )
        return PayoutCalculation(**response.json())

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

    def current_run(self) -> RunState | None:
        """The latest run, or None if there has been none."""
        run = self._send("GET", "/api/runs/current").json()
        return RunState(**run) if run else None

    def add_run_claim(self, run_id: int, claim_id: str) -> None:
        """Record that the run has started a claim."""
        self._send("POST", f"/api/runs/{run_id}/claims", {"claim_id": claim_id})

    def set_todos(self, run_id: int, todos: list[TodoItem]) -> None:
        body = {"todos": [todo.model_dump() for todo in todos]}
        self._send("PUT", f"/api/runs/{run_id}/todos", body)

    def finish_run(self, run_id: int, summary: str) -> None:
        self._send("POST", f"/api/runs/{run_id}/finish", {"summary": summary})
