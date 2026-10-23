# Status

The claims pilot, built phase by phase from `docs/PLAN.md`. Done so far: the backend's records, claim workflow and payment rule.

## Run it

- `npm run dev` starts the backend on port 8000 and the dashboard on port 5173.
- `uv run -m backend.seed` resets the database (`backend/undercover.db`, or `UNDERCOVER_DB`) to the 25 waiting claims in `data/`. The backend loads it by itself when the file is missing.
- `npm run check` runs every check.

## What's built

- `backend/`: FastAPI and SQLite. Amounts go over the API as dollar strings, such as `"420.00"`.
  - `GET /api/claims` and `GET /api/claims/{claim_id}`: the queue and one claim in full
  - `GET /api/policies/{policy_id}` and `GET /api/customers/{customer_id}`: the policy, and the customer's name and earlier claims (no contact details)
  - `POST /api/claims/{claim_id}/start` and `/release`: waiting to in progress, and back
  - `GET` and `POST /api/claims/{claim_id}/steps`: what the agent did on a claim, oldest first
  - `POST /api/claims/{claim_id}/decision`: approve, decline or refer, with the payout rounded to the cent, an explanation and a policy section. A payout over the $1,000.00 limit (from `data/company.json`) leaves the claim `awaiting_sign_off`
  - `POST /api/claims/{claim_id}/payment`: records a payment of the approved payout. A payout over the limit is refused with a 403, so the payment stays blocked until a handler signs off. Other bad payments (not approved, wrong amount, already paid) get a 409
  - `GET /api/policy-wording` and `GET /api/instructions`: plain text
- `agent/`: the skeleton's entry point `run(claim_id, thread_id)`, with one tool that calls the health route.
- `dashboard/`: one page that shows whether the backend is up.
- `e2e/`: one test of that page.

Loaded from `data/`: the claims, policies and customers, and the policy wording. Never loaded: `data/evals/`, `data/security/` and the claims manual.
