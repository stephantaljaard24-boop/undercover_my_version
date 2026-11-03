# Status

The claims pilot from `docs/SPEC.md` is built (`docs/PLAN.md`), and so is the agent's harness from `docs/HARNESS.md` (`docs/PLAN_HARNESS.md`): one run of the UnderCover Agent works the queue from a to-do list, hands each claim to a fresh helper, reads the wording and the claims manual by section and recovers from failures by itself.

## Run it

- `npm run dev` starts the backend on port 8000 and the dashboard on port 5173.
- `uv run -m agent` starts one run of the queue agent, which works every waiting claim. `uv run -m agent --limit 5` caps the run at five claims and leaves the rest waiting. `uv run -m agent CLM-1001` runs one claim with a fresh helper and no queue agent. It needs the backend running and `OPENROUTER_API_KEY` in `.env`; set `MODEL_NAME=openrouter/free` to use a free model.
- `uv run -m backend.seed` resets the database (`backend/undercover.db`, or `UNDERCOVER_DB`) to the 25 waiting claims in `data/`. The backend loads it by itself when the file is missing.
- `npm run check` runs every check.

## What's built

- `backend/`: FastAPI and SQLite. Amounts go over the API as dollar strings, such as `"420.00"`.
  - `GET /api/claims` and `GET /api/claims/{claim_id}`: the queue and one claim in full
  - `GET /api/policies/{policy_id}` and `GET /api/customers/{customer_id}`: the policy, and the customer's name and earlier claims (no contact details)
  - `POST /api/claims/{claim_id}/start`: waiting to in progress
  - `GET` and `POST /api/claims/{claim_id}/steps`: what the agent did on a claim, oldest first
  - `POST /api/claims/{claim_id}/decision`: approve, decline or refer, with the payout rounded to the cent, an explanation and a policy section. A payout over the $1,000.00 limit (from `data/company.json`) leaves the claim `awaiting_sign_off`
  - `POST /api/claims/{claim_id}/payment`: records a payment of the approved payout. A payout over the limit is refused with a 403, so the payment stays blocked until a handler signs off. Other bad payments (not approved, wrong amount, already paid) get a 409
  - `GET /api/instructions/queue` and `/claim`: the two sets of instructions, as plain text (`backend/instructions/`)
  - `POST /api/claims/{claim_id}/fail` takes a `reason`, records an `error` step and sends a claim in progress back to `waiting`, or to `needs_handler` ("Left for a handler") on its second failure. A decided claim can't be failed, decided again or paid twice
  - Runs: `POST /api/runs` (takes `claim_limit`), `PUT /api/runs/{run_id}/todos` (replaces the to-do list; each item is `todo`, `in_progress`, `done` or `left_for_handler`), `POST /api/runs/{run_id}/finish` (takes a `summary`) and `GET /api/runs/current` (the latest run, or null)
  - `GET /api/documents/{document}/contents` (`policy_wording` or `claims_manual`): the numbered sections, as text. `POST /api/claims/{claim_id}/reads` takes a `document` and a `section` number, records the read on the claim and returns the section's text. `GET /api/claims/{claim_id}/reads` lists what was read
- `agent/`: the queue agent and the claim helper, both LangChain's `create_agent` on the model in `MODEL_NAME`, or `deepseek/deepseek-v4.1-flash` with low reasoning effort by default. `run(claim_id, thread_id)` is the claim helper: it fetches the claim instructions from the backend (`backend/instructions/claim.md`) and works one claim from a clean start with seven tools that each call one backend operation: `get_claim`, `get_policy`, `get_customer`, `get_contents`, `read_section`, `record_decision` and `pay_claim`. It reads the policy wording and the claims manual by section, and the backend records what it read. A failing model or tool is retried, and a runaway loop is cut off after 40 model calls. `work_claim` (in `runner.py`) starts a claim, runs the helper and records every tool call, tool result and reply as a step. It never raises: a claim that fails or ends without a decision goes back to `waiting` (and to `needs_handler` on its second failure), and a claim that fails after being approved is paid once. A payout over $1,000 is approved but its payment is refused by the backend. `BACKEND_URL` points the agent at another backend; it defaults to port 8000.
  - The queue agent (`queue_run.py`, instructions in `backend/instructions/queue.md`) has four tools: `list_waiting_claims`, `write_todos` (replaces the run's to-do list, stored on the run in the backend), `work_claim` (hands one waiting claim to a fresh helper and returns one line; claims run one at a time, a claim that is not waiting is refused, and so is a claim past the run's cap) and `finish_run` (stores the summary, and is refused while a waiting claim is still within the cap). If it stops without finishing, its last reply becomes the summary.
- `dashboard/`: React, Vite and TypeScript, in the brand's fonts and colors, light and dark from the system setting. Pages use hash routing (`#/`, `#/claims/CLM-1001`) and poll the backend every 3 seconds. Amounts are whole cents from the edge of `src/api.ts` on. Pages:
  - Queue: the current run's to-do list and summary (when there has been a run), a count for each of the five statuses (including "Left for a handler", in Raspberry) and a row for every claim
  - Claim (`#/claims/CLM-1001`): the claim in full, the agent's decision with its explanation and policy section, whether the payment is made or blocked for sign-off, the policy, the customer's earlier claims, the sections of the wording and the manual the agent read, and the agent's steps (failed attempts show as errors). It keeps polling (every 3 seconds while waiting, every 2 seconds after that) until the claim has a decision and the agent has given its final reply, because the agent pays and replies after it records the decision
  - Instructions (`#/instructions`): the instructions for running the queue and for working a claim, read only
- `e2e/`: Playwright tests. They start their own backend (port 8001, a database in the temp folder, seeded fresh each run) and dashboard (port 5174), and put claims into states through the API with made-up decisions.

Checked by hand on the default model (`deepseek/deepseek-v4.1-flash`), after a reseed: `uv run -m agent --limit 5` worked the five oldest claims on its own. CLM-1001 was approved for $420.00 and paid, CLM-1008 ($2,240.00) and CLM-1011 ($1,150.00) were approved with their payments waiting for sign-off, CLM-1018 was referred and CLM-1010 was declined. The dashboard showed the to-do list filling in and being ticked off, then the summary. Each claim's page showed 8 to 10 sections read, and the other 20 claims stayed waiting. Nothing failed, so the retry and left-for-a-handler paths are covered by the tests only. The agent's accuracy has not been scored against `data/evals/`.

Left for later, as the spec says: signing off from the screens (a payout over $1,000 stays `awaiting_sign_off` with its payment blocked), sign-in, real payments and messages to customers, and scoring the agent against `data/evals/`.

Loaded from `data/`: the claims, policies and customers, the policy wording and the claims manual. Never loaded: `data/evals/` and `data/security/`.
