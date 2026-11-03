from backend.documents import sections
from backend.seed import seed


def read(client, section, document="claims_manual", claim_id="CLM-1001"):
    return client.post(
        f"/api/claims/{claim_id}/reads", json={"document": document, "section": section}
    )


def test_contents_list_every_section(client):
    wording = client.get("/api/documents/policy_wording/contents")
    assert wording.headers["content-type"].startswith("text/plain")
    lines = wording.text.splitlines()
    assert len(lines) == 12
    assert lines[2] == "3. Trip Delay"
    manual = client.get("/api/documents/claims_manual/contents").text.splitlines()
    assert len(manual) == 14
    assert manual[8] == "9. Repeat claims"


def test_read_section_returns_just_that_section(client):
    text = read(client, "9").text
    assert text.startswith("## 9. Repeat claims")
    assert "third claim within any 12 month period" in text
    assert "10. Meals without receipts" not in text


def test_the_last_section_is_read_to_the_end(client):
    assert read(client, "14").text.endswith("is treated as not yet made.")


def test_reads_are_recorded_once_in_order(client):
    read(client, "9")
    read(client, "5")
    read(client, "9")
    read(client, "3", "policy_wording")
    assert client.get("/api/claims/CLM-1001/reads").json() == [
        {"document": "claims_manual", "section": "9", "title": "Repeat claims"},
        {
            "document": "claims_manual",
            "section": "5",
            "title": "Documents and document requests",
        },
        {"document": "policy_wording", "section": "3", "title": "Trip Delay"},
    ]
    assert client.get("/api/claims/CLM-1002/reads").json() == []


def test_unknown_things_are_404(client):
    assert client.get("/api/documents/evals/contents").status_code == 404
    assert read(client, "99").status_code == 404
    assert read(client, "1", "evals").status_code == 404
    assert read(client, "1", claim_id="CLM-0000").status_code == 404
    assert client.get("/api/claims/CLM-0000/reads").status_code == 404
    assert client.get("/api/claims/CLM-1001/reads").json() == []


def test_seed_clears_the_reads(client):
    read(client, "9")
    seed()
    assert client.get("/api/claims/CLM-1001/reads").json() == []


def test_only_the_two_documents_are_served():
    assert sections("policy_wording")["10"][0] == "How we work out your payment"
