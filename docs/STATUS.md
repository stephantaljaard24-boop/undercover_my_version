# Status

The claims pilot from `docs/SPEC.md` is built: the backend, the UnderCover Agent and the dashboard, to the plan in `docs/PLAN.md`.

## Run it

- `npm run dev` starts the backend on port 8000 and the dashboard on port 5173.
- `uv run -m agent` works through every waiting claim, one at a time, and prints a line for each. `uv run -m agent CLM-1001` runs one claim. It needs the backend running and `OPENROUTER_API_KEY` in `.env`; set `MODEL_NAME=openrouter/free` to use a free model.
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
  - `GET /api/documents/{document}/contents` (`policy_wording` or `claims_manual`): the numbered sections, as text. `POST /api/claims/{claim_id}/reads` takes a `document` and a `section` number, records the read on the claim and returns the section's text. `GET /api/claims/{claim_id}/reads` lists what was read
- `agent/`: LangChain's `create_agent`. `run(claim_id, thread_id)` fetches the instructions from the backend (`backend/instructions.md`) and works one claim with six tools that each call one backend operation: `get_claim`, `get_policy`, `get_customer`, `get_policy_wording`, `record_decision` and `pay_claim`. The runner, not the model, starts and releases claims and records every tool call, tool result and reply as a step; a claim that ends without a decision goes back to waiting. A payout over $1,000 is approved but its payment is refused by the backend.
- `dashboard/`: React, Vite and TypeScript, in the brand's fonts and colors, light and dark from the system setting. Pages use hash routing (`#/`, `#/claims/CLM-1001`) and poll the backend every 3 seconds. Amounts are whole cents from the edge of `src/api.ts` on. Pages:
  - Queue: a count for each status and a row for every claim
  - Claim (`#/claims/CLM-1001`): the claim in full, the agent's decision with its explanation and policy section, whether the payment is made or blocked for sign-off, the policy, the customer's earlier claims, and the agent's steps. It keeps polling (every 3 seconds while waiting, every 2 seconds after that) until the claim has a decision and the agent has given its final reply, because the agent pays and replies after it records the decision
  - Instructions (`#/instructions`): the agent's instructions, read only
- `e2e/`: Playwright tests. They start their own backend (port 8001, a database in the temp folder, seeded fresh each run) and dashboard (port 5174), and put claims into states through the API with made-up decisions.

Checked by hand with `MODEL_NAME=openrouter/free`: CLM-1001 was approved for $420.00 and paid, and CLM-1002 was approved for $580.00 and paid, with the dashboard showing the steps and the result as they happened. The agent's accuracy has not been scored against `data/evals/`.

Left for later, as the spec says: signing off from the screens (a payout over $1,000 stays `awaiting_sign_off` with its payment blocked), the claims manual, sign-in, real payments and messages to customers.

Loaded from `data/`: the claims, policies and customers, and the policy wording. Never loaded: `data/evals/`, `data/security/` and the claims manual.
