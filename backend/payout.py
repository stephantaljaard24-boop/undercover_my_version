"""UnderCover's payout rules for an approved claim.

The rules come from section 10 of the policy wording, the plan limits in
data/plans.json and sections 6, 7 and 10 of the claims manual.
"""

from decimal import ROUND_HALF_UP, Decimal
from functools import cache
from math import ceil
from typing import Any

from backend import rules
from backend.data import load_json
from backend.models import (
    CENT,
    Benefit,
    CalcStep,
    PayoutCalculation,
    PayoutLine,
    Policy,
)

CASH_LIMIT = Decimal(100)
HOTEL_NIGHT_LIMIT = Decimal(350)

BENEFIT_MAXIMUM: dict[Benefit, str] = {
    "trip_cancellation": "trip_cancellation_max",
    "trip_interruption": "trip_cancellation_max",
    "trip_delay": "trip_delay_max",
    "baggage_delay": "baggage_delay_max",
    "baggage": "baggage_max",
    "passport": "passport_max",
    "emergency_medical": "emergency_medical_max",
}


@cache
def plan_data() -> dict[str, Any]:
    """The plans, the add-ons and the benefits the deductible applies to."""
    return load_json("plans.json")


def plan_of(policy: Policy) -> dict[str, Any]:
    """Return the limits of the policy's plan."""
    return next(p for p in plan_data()["plans"] if p["plan"] == policy.plan)


def meal_allowance() -> Decimal:
    """Return what a traveler may claim for meals without receipts, for each day."""
    return load_json("company.json")["meal_allowance_without_receipts"]["amount"]


def electronics_limit(policy: Policy) -> Decimal:
    """Return the most paid for one electronic item under the policy."""
    if "electronics_plus" in policy.add_ons:
        add_ons = {a["add_on"]: a for a in plan_data()["add_ons"]}
        return add_ons["electronics_plus"]["electronics_per_item_limit"]
    return plan_of(policy)["per_item_limit"]


def limit_for(line: PayoutLine, policy: Policy) -> Decimal | None:
    """Return the most paid for one line, or None when the line has no limit."""
    travelers = len(policy.travelers)
    match line.kind:
        case "item":
            return plan_of(policy)["per_item_limit"] * line.quantity
        case "electronics":
            return electronics_limit(policy) * line.quantity
        case "hotel":
            return HOTEL_NIGHT_LIMIT * ceil(travelers / 2) * line.nights
        case "meals_without_receipts":
            return meal_allowance() * travelers * ceil(line.hours / 24)
        case _:
            return None


def eligible_amount(line: PayoutLine, policy: Policy) -> CalcStep:
    """Return a line's step: the amount claimed, or its limit if that is lower."""
    limit = limit_for(line, policy)
    if limit is not None and line.amount > limit:
        return CalcStep(
            step=f"{line.description}, limited to ${limit:,.2f}", amount=limit
        )
    return CalcStep(step=line.description, amount=line.amount)


def benefit_maximum(policy: Policy, benefit: Benefit) -> Decimal:
    """Return the most the plan pays for a benefit.

    Trip cancellation and interruption are also capped at the trip cost.
    """
    maximum = plan_of(policy)[BENEFIT_MAXIMUM[benefit]]
    if benefit in ("trip_cancellation", "trip_interruption"):
        return min(maximum, policy.trip.trip_cost)
    return maximum


def work_out_payout(
    policy: Policy,
    benefit: Benefit,
    lines: list[PayoutLine],
    paid_by_others: Decimal,
) -> PayoutCalculation:
    """Work out the payout on an approved claim, following section 10 of the wording."""
    calculation = [
        eligible_amount(line, policy) for line in lines if line.kind != "cash"
    ]
    cash = sum((line.amount for line in lines if line.kind == "cash"), Decimal(0))
    if cash:
        label = f"Cash, up to ${CASH_LIMIT:,.0f} in all"
        calculation.append(CalcStep(step=label, amount=min(cash, CASH_LIMIT)))
    total = sum((entry.amount for entry in calculation), Decimal(0))

    if paid_by_others:
        calculation.append(
            CalcStep(
                step="Less what others have paid or refunded", amount=-paid_by_others
            )
        )
        total -= paid_by_others

    if benefit in plan_data()["deductible_applies_to"] and total > 0:
        deductible = min(plan_of(policy)["deductible"], total)
        if deductible:
            calculation.append(CalcStep(step="Less the deductible", amount=-deductible))
            total -= deductible

    maximum = benefit_maximum(policy, benefit)
    if total > maximum:
        label = f"Less the amount over the maximum of ${maximum:,.0f}"
        calculation.append(CalcStep(step=label, amount=maximum - total))
        total = maximum

    if total < 0:
        calculation.append(CalcStep(step="Nothing is left to pay", amount=-total))
        total = Decimal(0)

    payout = total.quantize(CENT, rounding=ROUND_HALF_UP)
    return PayoutCalculation(
        calculation=calculation,
        payout=payout,
        needs_sign_off=payout > rules.approval_limit(),
    )
