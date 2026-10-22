"""The shapes of what the API takes and returns. Amounts are exact dollars."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, PlainSerializer, model_validator

CENT = Decimal("0.01")

Money = Annotated[
    Decimal,
    PlainSerializer(lambda d: str(d.quantize(CENT)), return_type=str),
]

Status = Literal["waiting", "in_progress", "awaiting_sign_off", "decided"]
Verdict = Literal["approve", "decline", "refer"]
StepKind = Literal["tool_call", "tool_result", "reply"]


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


class Payment(BaseModel):
    amount: Money


class ClaimDetail(Claim):
    status: Status
    decision: Decision | None
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


class Step(BaseModel):
    kind: StepKind
    text: str
