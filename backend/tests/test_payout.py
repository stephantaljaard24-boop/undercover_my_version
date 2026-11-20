from decimal import Decimal

from backend import rules

# CLM-1001 is premium with no add-ons: a $300 limit for each item, a $1,500 baggage
# maximum, a $50 deductible on baggage and emergency medical, one traveler.
PREMIUM = "CLM-1001"
PREMIUM_ELECTRONICS = "CLM-1009"
ECONOMY = "CLM-1007"
FIRST_SIX_TRAVELERS = "CLM-1015"
CHEAP_TRIP = "CLM-1010"


def line(description, amount, kind="item", **counts):
    """A line of a claim. The counts are quantity, nights and hours."""
    return {
        "description": description,
        "amount": amount,
        "kind": kind,
        "quantity": 1,
        "nights": 0,
        "hours": 0,
        **counts,
    }


def calculate(client, claim_id, benefit, lines, paid_by_others="0.00"):
    body = {"benefit": benefit, "lines": lines, "paid_by_others": paid_by_others}
    return client.post(f"/api/claims/{claim_id}/payout-calculation", json=body)


def payout(client, claim_id, benefit, lines, paid_by_others="0.00"):
    response = calculate(client, claim_id, benefit, lines, paid_by_others)
    assert response.status_code == 200
    return response.json()["payout"]


def test_the_calculation_is_shown_step_by_step(client):
    lines = [line("Suitcase", "239.99"), line("Three shirts", "74.97", quantity=3)]
    result = calculate(client, PREMIUM, "baggage", lines, "100.00").json()
    assert result == {
        "calculation": [
            {"step": "Suitcase", "amount": "239.99"},
            {"step": "Three shirts", "amount": "74.97"},
            {"step": "Less what others have paid or refunded", "amount": "-100.00"},
            {"step": "Less the deductible", "amount": "-50.00"},
        ],
        "payout": "164.96",
        "needs_sign_off": False,
    }


def test_an_unknown_claim_is_404(client):
    assert calculate(client, "CLM-0000", "baggage", []).status_code == 404


def test_a_line_must_have_every_field(client):
    body = {
        "benefit": "baggage",
        "lines": [{"description": "Suitcase", "amount": "10.00", "kind": "item"}],
        "paid_by_others": "0.00",
    }
    response = client.post(f"/api/claims/{PREMIUM}/payout-calculation", json=body)
    assert response.status_code == 422


def test_an_item_is_limited_to_the_plans_per_item_limit(client):
    result = calculate(client, PREMIUM, "baggage", [line("Camera bag", "450.00")])
    assert result.json()["calculation"][0] == {
        "step": "Camera bag, limited to $300.00",
        "amount": "300.00",
    }
    assert result.json()["payout"] == "250.00"


def test_several_items_in_one_line_have_a_limit_each(client):
    assert payout(
        client, PREMIUM, "baggage", [line("Jackets", "1000", quantity=3)]
    ) == ("850.00")


def test_electronics_have_the_add_ons_limit(client):
    laptop = [line("Laptop", "1100.00", kind="electronics")]
    assert payout(client, PREMIUM_ELECTRONICS, "baggage", laptop) == "1050.00"
    assert payout(client, PREMIUM, "baggage", laptop) == "250.00"


def test_cash_is_limited_to_one_hundred_in_all(client):
    cash = [line("Wallet", "80.00", kind="cash"), line("Pocket", "70.00", kind="cash")]
    assert payout(client, PREMIUM, "baggage", cash) == "50.00"


def test_hotel_nights_are_limited_for_each_room(client):
    hotel = [line("Hotel", "900.00", kind="hotel", nights=2)]
    assert payout(client, PREMIUM, "trip_delay", hotel) == "700.00"
    six = [line("Hotel", "2000.00", kind="hotel", nights=1)]
    assert payout(client, FIRST_SIX_TRAVELERS, "trip_delay", six) == "1050.00"


def test_meals_without_receipts_are_limited_for_each_traveler_and_day(client):
    meals = [line("Meals", "120.00", kind="meals_without_receipts", hours=30)]
    assert payout(client, PREMIUM, "trip_delay", meals) == "70.00"


def test_the_deductible_applies_only_to_baggage_and_emergency_medical(client):
    expense = [line("Bill", "200.00", kind="expense")]
    assert payout(client, PREMIUM, "trip_delay", expense) == "200.00"
    assert payout(client, PREMIUM, "emergency_medical", expense) == "150.00"
    assert payout(client, ECONOMY, "baggage", [line("Hat", "60.00")]) == "0.00"


def test_the_payout_never_goes_below_zero(client):
    result = calculate(
        client, PREMIUM, "trip_delay", [line("Bill", "100.00", "expense")], "250.00"
    ).json()
    assert result["calculation"][-1] == {
        "step": "Nothing is left to pay",
        "amount": "150.00",
    }
    assert result["payout"] == "0.00"


def test_the_payout_is_capped_at_the_benefit_maximum_and_the_trip_cost(client):
    expense = [line("Prepaid trip", "5000.00", kind="expense")]
    assert payout(client, ECONOMY, "trip_cancellation", expense) == "1500.00"
    capped = calculate(client, CHEAP_TRIP, "trip_cancellation", expense).json()
    assert capped["payout"] == "1900.00"
    assert capped["calculation"][-1]["step"] == (
        "Less the amount over the maximum of $1,900"
    )


def test_a_payout_over_the_limit_needs_sign_off(client):
    at_limit = calculate(
        client, PREMIUM, "emergency_medical", [line("Bill", "1050.00", "expense")]
    )
    assert at_limit.json()["payout"] == "1000.00"
    assert at_limit.json()["needs_sign_off"] is False
    over = calculate(
        client, PREMIUM, "emergency_medical", [line("Bill", "1050.01", "expense")]
    )
    assert over.json()["payout"] == "1000.01"
    assert over.json()["needs_sign_off"] is True


def test_the_limit_comes_from_the_approval_rule(client, monkeypatch):
    monkeypatch.setattr(rules, "approval_limit", lambda: Decimal(500))
    result = calculate(
        client, PREMIUM, "trip_delay", [line("Bill", "600.00", "expense")]
    )
    assert result.json()["needs_sign_off"] is True
