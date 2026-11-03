from fastapi.testclient import TestClient

from backend import db
from backend.main import app
from backend.seed import seed


def test_queue_is_the_twenty_five_claims(client):
    claims = client.get("/api/claims").json()
    assert [c["claim_id"] for c in claims] == [f"CLM-{n}" for n in range(1001, 1026)]
    assert {c["status"] for c in claims} == {"waiting"}
    assert claims[0]["customer_name"] == "Maya Patel"
    assert claims[0]["decision"] is None
    assert claims[0]["payout"] is None


def test_the_security_claim_is_not_loaded(client):
    assert client.get("/api/claims/CLM-1901").status_code == 404


def test_claim_in_full(client):
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["status"] == "waiting"
    assert claim["decision"] is None
    assert claim["payment"] is None
    assert len(claim["items"]) == 3
    assert len(claim["documents"]) == 4
    assert claim["story"].startswith("My flight home from Rome")


def test_amounts_are_exact_strings(client):
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["amount_claimed"] == "420.00"
    assert [i["amount"] for i in claim["items"]] == ["245.00", "95.00", "80.00"]


def test_policy(client):
    policy = client.get("/api/policies/POL-2001").json()
    assert policy["plan"] == "premium"
    assert policy["travelers"] == ["Maya Patel"]
    assert policy["trip"]["trip_cost"] == "3100.00"


def test_customer_has_history_and_no_contact_details(client):
    customer = client.get("/api/customers/CUS-3001").json()
    assert customer["name"] == "Maya Patel"
    assert customer["previous_claims"][0]["claim_id"] == "CLM-0412"
    assert customer["previous_claims"][0]["amount_paid"] == "140.00"
    assert "email" not in customer
    assert "date_of_birth" not in customer


def test_unknown_records_are_404(client):
    assert client.get("/api/claims/CLM-0000").status_code == 404
    assert client.get("/api/policies/POL-0000").status_code == 404
    assert client.get("/api/customers/CUS-0000").status_code == 404


def test_texts(client):
    assert client.get("/api/instructions").status_code == 404
    assert client.get("/api/policy-wording").status_code == 404
    assert client.post("/api/claims/CLM-1001/release").status_code == 404


def test_seed_resets_the_database(client):
    conn = db.connect()
    with conn:
        conn.execute("UPDATE claims SET status = 'decided'")
    conn.close()
    seed()
    assert {c["status"] for c in client.get("/api/claims").json()} == {"waiting"}


def test_database_is_created_on_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "new.db"))
    with TestClient(app) as started:
        assert len(started.get("/api/claims").json()) == 25


def test_every_operation_has_an_id_and_no_optional_inputs(client):
    spec = client.get("/openapi.json").json()
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            assert operation.get("operationId"), (method, path)
            assert operation.get("summary"), (method, path)
            for parameter in operation.get("parameters", []):
                assert parameter["required"], (method, path)
