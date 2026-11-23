"""The shapes of what the API takes and returns. Amounts are exact dollars."""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, PlainSerializer, model_validator

CENT = Decimal("0.01")

Money = Annotated[
    Decimal,
    PlainSerializer(lambda d: str(d.quantize(CENT)), return_type=str),
]

Status = Literal[
    "waiting", "in_progress", "awaiting_sign_off", "decided", "needs_handler"
]
Verdict = Literal["approve", "decline", "refer"]
StepKind = Literal["tool_call", "tool_result", "reply", "error"]
TodoStatus = Literal["todo", "in_progress", "done", "left_for_handler"]


class Item(BaseModel):
    description: str
    category: str
    amount: Money


class Document(BaseModel):
    name: str
    type: str
    content: str


class Claim(BaseModel):
    claim_id: str
    policy_id: str
    customer_id: str
    claim_type: str
    submitted_on: date
    incident_date: date
    incident_location: str
    summary: str
    story: str
    items: list[Item]
    amount_claimed: Money
    documents: list[Document]


class Decision(BaseModel):
    decision: Verdict
    payout: Money
    explanation: Annotated[str, Field(min_length=1)]
    policy_section: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def check_payout(self) -> Self:
        self.payout = self.payout.quantize(CENT, rounding=ROUND_HALF_UP)
        if self.decision == "approve" and self.payout <= 0:
            raise ValueError("An approval needs a payout above zero")
        if self.decision != "approve" and self.payout != 0:
            raise ValueError("A decline or a referral has a payout of zero")
        return self


class Amount(BaseModel):
    amount: Money


class SignOff(BaseModel):
    handler_id: str
    signed_off_by: str
    signed_off_at: datetime


class Payment(BaseModel):
    amount: Money
    signed_off_by: str | None = None
    signed_off_at: datetime | None = None


class Handler(BaseModel):
    handler_id: str
    name: str
    role: str
    can_approve_over_limit: bool


class HandlerChoice(BaseModel):
    handler_id: str


class ClaimDetail(Claim):
    status: Status
    thread_id: str | None
    decision: Decision | None
    sign_off: SignOff | None
    payment: Payment | None


class ClaimSummary(BaseModel):
    claim_id: str
    customer_name: str
    claim_type: str
    summary: str
    submitted_on: date
    amount_claimed: Money
    status: Status
    decision: Verdict | None
    payout: Money | None


class Trip(BaseModel):
    destination: str
    departs_on: date
    returns_on: date
    trip_cost: Money


class Policy(BaseModel):
    policy_id: str
    customer_id: str
    plan: str
    add_ons: list[str]
    purchased_on: date
    sold_through: str
    trip: Trip
    travelers: list[str]
    status: str


class PreviousClaim(BaseModel):
    claim_id: str
    filed_on: date
    incident_date: date
    claim_type: str
    summary: str
    outcome: str
    amount_paid: Money


class Customer(BaseModel):
    customer_id: str
    name: str
    customer_since: date
    previous_claims: list[PreviousClaim]


Benefit = Literal[
    "trip_cancellation",
    "trip_interruption",
    "trip_delay",
    "baggage_delay",
    "baggage",
    "passport",
    "emergency_medical",
]
LineKind = Literal[
    "item", "electronics", "cash", "expense", "hotel", "meals_without_receipts"
]


class PayoutLine(BaseModel):
    description: str
    amount: Money
    quantity: Annotated[int, Field(ge=1)]
    kind: LineKind
    nights: Annotated[int, Field(ge=0)]
    hours: Annotated[Decimal, Field(ge=0)]


class PayoutRequest(BaseModel):
    benefit: Benefit
    lines: list[PayoutLine]
    paid_by_others: Money


class CalcStep(BaseModel):
    step: str
    amount: Money


class PayoutCalculation(BaseModel):
    calculation: list[CalcStep]
    payout: Money
    needs_sign_off: bool


class Step(BaseModel):
    kind: StepKind
    text: str


class SectionRef(BaseModel):
    document: str
    section: str


class SectionRead(SectionRef):
    title: str


class Failure(BaseModel):
    reason: Annotated[str, Field(min_length=1)]


class Todo(BaseModel):
    text: Annotated[str, Field(min_length=1)]
    status: TodoStatus


class TodoList(BaseModel):
    todos: list[Todo]


class ClaimLimit(BaseModel):
    claim_limit: Annotated[int, Field(ge=1)]


class RunClaim(BaseModel):
    claim_id: str


class Summary(BaseModel):
    summary: Annotated[str, Field(min_length=1)]


class Run(BaseModel):
    run_id: int
    claim_limit: int
    todos: list[Todo]
    summary: str | None
    finished: bool
    started: list[str]
