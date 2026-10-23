# Plan: the claims pilot

The pilot builds three things on the skeleton: a backend that holds the claims queue and enforces the payment rule, the UnderCover Agent that works the queue from the command line, and a dashboard where the claims team watches it. It works from `docs/SPEC.md`, in six phases, each building on the last.

## Open questions and assumptions

1. **Claim statuses.** The four the spec names become `waiting`, `in_progress`, `awaiting_sign_off` and `decided`. Every claim in `data/claims.json` is `open`, which loads as `waiting`.
2. **Referred claims are decided.** A refer is a decision like the other two, so a referred claim shows as `decided` with the decision `refer`. A handler picks it up from there, outside the system.
3. **Which approvals wait for sign-off.** A payout strictly over the limit waits; exactly $1,000.00 does not. The limit is read from `payout_approval_limit` in `data/company.json`, not written into the code.
4. **Paying a claim.** "No real payments" means the backend records a payment, and nothing more. The agent pays every claim it approves through the separate pay operation; for a payout over the limit the backend refuses with 403 and the claim stays `awaiting_sign_off`. The backend also refuses a payment that doesn't match the approved payout, a second payment, and a payment on a claim that wasn't approved.
5. **Amounts in the API.** Amounts go over the API as dollar strings, such as `"420.00"`, from Python `Decimal`. That keeps the agent working in the dollars the policy wording uses. The dashboard turns each one into whole cents as it arrives and formats cents for display, so no float ever holds money. The payout is rounded to the cent, half up, when the decision is recorded.
6. **The agent's instructions.** They live in the backend as `backend/instructions.md` and are served read only by `GET /api/instructions`. The agent fetches them at the start of each claim and uses them as its system prompt, so the agent reaches them only through the API, and the dashboard shows the same text.
7. **What the agent reads.** The claim, its policy, the customer with their earlier claims (`previous_claims` in `data/customers.json`), and the full `data/policy_wording.md`. The policy wording holds the plan limits, so `plans.json` isn't served separately. Not loaded at all: the claims manual (not for now), `data/evals/`, `data/security/` (kept for security testing), `knowledge.json`, `policy_wording_short.md` and `handlers.json` (no sign-in or sign-off yet).
8. **The steps.** The runner records each step as the agent goes, not the model: every tool call, every tool result (shortened) and the agent's final reply, posted to the backend. The model can't skip or fake a step that way.
9. **When the agent stops without a decision.** If the agent finishes or fails without recording a decision, the runner puts the claim back to `waiting` so the next run picks it up, and reports it. A failure still stops the run with its error.
10. **The command line.** `uv run -m agent` works through every waiting claim, one at a time. `uv run -m agent CLM-1001` runs one claim, which is what the hand check with a real model uses. Each claim gets a fresh thread id.
11. **Live updates.** The dashboard polls: the queue every 3 seconds, and a claim's page every 2 seconds while it is in progress. That is simpler than websockets and fast enough for a person watching.
12. **The database.** SQLite through Python's own `sqlite3`, at the path in `UNDERCOVER_DB`, by default `backend/undercover.db` (already ignored by git). The backend loads it from `data/` the first time it starts, and `uv run -m backend.seed` resets it to the starting queue.
13. **The end-to-end tests get their own database.** They run the backend on port 8001 with its own database, reset at the start of each run, and the dashboard on port 5174, so they never touch the data you use with `npm run dev`. They put claims into each state through the API, with made-up decisions that are not the handlers' answers.
14. **Status colors.** Brand order for four things: waiting Sea Green, in progress Marigold, waiting for sign-off Coral, decided Cerulean. Decisions: approve Sea Green, refer Marigold, decline Coral.
15. **The agent's accuracy is not judged here.** Scoring against `data/evals/` is a later step. The pilot's checks are that the agent decides, explains, cites a section and obeys the payment rule.

## Phase 1: the records in the backend

**What it builds.** The SQLite store, loading from `data/`, and the read operations the agent and the dashboard share.

- `backend/db.py`: opens a connection per request, creates the tables (`claims`, `policies`, `customers`, `decisions`, `payments`, `steps`), and loads the seed data. JSON amounts load as `Decimal` (`parse_float=Decimal`) and are stored as text.
- `backend/seed.py`: `uv run -m backend.seed` resets the database.
- `backend/models.py`: Pydantic models for every response.
- `backend/main.py`: on startup, loads the database if the file is missing. New operations, each with an `operation_id`, a one-line docstring and no optional inputs:

| Operation | Route | Returns |
|---|---|---|
| `list_claims` | `GET /api/claims` | Every claim with its id, customer name, type, summary, submitted date, amount claimed, status, and its decision and payout once decided |
| `get_claim` | `GET /api/claims/{claim_id}` | The whole claim, its status, its decision and its payment |
| `get_policy` | `GET /api/policies/{policy_id}` | The policy |
| `get_customer` | `GET /api/customers/{customer_id}` | The customer and their earlier claims |
| `get_policy_wording` | `GET /api/policy-wording` | The policy wording as text |
| `get_instructions` | `GET /api/instructions` | The agent's instructions as text |

`backend/instructions.md` starts as a placeholder here; Phase 3 writes it.

**Why this way.** Storing each record's JSON as it comes from `data/`, next to columns for the parts that change (status, decision, payment, steps), keeps the schema small while the business data stays as UnderCover wrote it.

**Success criteria**

- [x] `uv run pytest -q backend` passes, with tests for each new operation, 404 for an unknown claim, policy or customer, and the reset.
- [x] A test confirms that nothing from `data/evals/` or `data/security/` is loaded: the queue is exactly CLM-1001 to CLM-1025.
- [x] A test confirms amounts come back as exact strings, such as `"420.00"` for CLM-1001's amount claimed.
- [x] With `npm run dev:backend` running, `curl.exe -s http://127.0.0.1:8000/api/claims` returns 25 claims, all `waiting`.
- [x] `curl.exe -s http://127.0.0.1:8000/api/claims/CLM-1001` returns the claim with its story, three items and four documents, `"status": "waiting"`, and no decision.
- [x] `curl.exe -s http://127.0.0.1:8000/openapi.json` shows an `operationId` and a summary for every operation, and no optional inputs.
- [x] `npm run check:python` passes.

## Phase 2: the claim workflow and the payment rule

**What it builds.** The operations that move a claim through the queue, and the block on payments over $1,000.

| Operation | Route | What it does |
|---|---|---|
| `start_claim` | `POST /api/claims/{claim_id}/start` | `waiting` to `in_progress`; 409 from any other status |
| `release_claim` | `POST /api/claims/{claim_id}/release` | `in_progress` back to `waiting`, for a run that ends without a decision; 409 otherwise |
| `add_step` | `POST /api/claims/{claim_id}/steps` | Records a step: `kind` (`tool_call`, `tool_result` or `reply`) and `text` |
| `list_steps` | `GET /api/claims/{claim_id}/steps` | The claim's steps, oldest first |
| `record_decision` | `POST /api/claims/{claim_id}/decision` | Takes `decision` (`approve`, `decline` or `refer`), `payout`, `explanation` and `policy_section`. Only on a claim in progress. An approval needs a payout above zero; a decline or refer needs a payout of zero. The payout is rounded to the cent. The claim becomes `awaiting_sign_off` if the payout is over the limit, otherwise `decided` |
| `pay_claim` | `POST /api/claims/{claim_id}/payment` | Takes `amount`. Records the payment only if the claim is approved, the amount equals the payout, it hasn't been paid, and the payout is within the limit. Over the limit: 403, "A payout over $1,000.00 needs a handler's sign-off." Otherwise 409 with the reason |

**Why this way.** The payment rule lives in the backend, in the one operation that pays, so it holds whatever the agent does: the agent can try to pay, and the system refuses. Recording the decision and paying are separate operations, as the tech stack asks, which lets an over-limit approval be recorded while its payment stays blocked.

**Success criteria**

- [x] `uv run pytest -q backend` passes, with a test for every rule above, including:
  - [x] Approve $420.00, then pay $420.00: the payment is recorded and the claim is `decided`.
  - [x] Approve $1,500.00, then pay $1,500.00: 403, no payment recorded, and the claim stays `awaiting_sign_off`.
  - [x] Approve exactly $1,000.00, then pay: the payment is recorded.
  - [x] Paying a declined or referred claim, paying the wrong amount, and paying twice each give 409.
  - [x] Deciding a claim that isn't in progress gives 409; a decline with a payout above zero gives 422.
  - [x] A payout of `"420.005"` is recorded as `"420.01"`.
- [x] By hand against `npm run dev:backend`: `curl.exe` to start CLM-1003, record an approval of `1500.00`, then pay `1500.00` returns 403, and `GET /api/claims/CLM-1003` shows `awaiting_sign_off` with no payment. Then `uv run -m backend.seed` puts it back to `waiting`.
- [x] `npm run check:python` passes.

## Phase 3: the UnderCover Agent and the queue runner

**What it builds.** The agent that decides one claim, and the command that works through the queue.

- `agent/tools.py`: the agent's tools, each a thin call to one backend operation: `get_claim`, `get_policy`, `get_customer`, `get_policy_wording`, `record_decision` and `pay_claim`. When the backend refuses (a 4xx), the tool returns the backend's reason to the model as text, so the agent learns that a payment is blocked instead of crashing.
- `agent/main.py`: `run(claim_id, thread_id)` fetches the instructions from `GET /api/instructions`, builds the agent with `create_agent` on the model from `MODEL_NAME` or `openai/gpt-6-luna` as now, streams it on the claim, and posts each step to the backend as it happens. The `check_backend` tool goes.
- `agent/__main__.py`: `uv run -m agent` lists the waiting claims and, one at a time, starts each claim, runs the agent and prints one line per claim, such as `CLM-1001: approve $420.00`. If a claim is still in progress afterwards, it releases it and says so. `uv run -m agent CLM-1001` does the same for one claim.
- `backend/instructions.md`: the agent's instructions. Read the claim, its policy, the customer's history and the policy wording; decide by the wording alone; work out the payout by section 10 (eligible amounts and per-item limits, less what others paid, less the deductible where it applies, capped at the benefit maximum); refer when a required document is missing or the claim needs judgment; record the decision with two or three sentences and the section it relies on; then pay an approved claim, knowing a payout over $1,000 will wait for a handler's sign-off.

**Why this way.** The tools only call the backend, so the agent sees what the API gives it and nothing else, and it can never reach `data/` or `data/evals/`. The runner, not the model, starts and releases claims and records the steps, so the queue and the step-by-step view stay right even when a model misbehaves.

**Success criteria**

- [ ] `uv run pytest -q agent` passes. Tests use a stub model and the backend's test client, and never call a model. They cover:
  - [ ] A stub that reads the claim, approves $420.00 and pays: the claim ends `decided`, paid, with its steps recorded in order.
  - [ ] A stub that approves $1,500.00 and pays: the pay tool returns the sign-off message, no payment is recorded, and the claim ends `awaiting_sign_off`.
  - [ ] A stub that ends without a decision: the runner releases the claim to `waiting`.
  - [ ] The queue runner takes every waiting claim in turn and skips claims in other states.
  - [ ] The agent's system prompt is the text from `GET /api/instructions`.
- [ ] A check by hand with a real model: with the backend running, `$env:MODEL_NAME="openrouter/free"; uv run -m agent CLM-1001` (on a Mac, `MODEL_NAME=openrouter/free uv run -m agent CLM-1001`) records a decision with an explanation and a policy section, and `GET /api/claims/CLM-1001/steps` lists its tool calls. I report what it decided. Then `uv run -m backend.seed`.
- [ ] `npm run check:python` passes.

## Phase 4: the dashboard's look and the queue

**What it builds.** The brand, simple page routing and the queue page.

- `dashboard/index.html` loads Instrument Sans, Instrument Serif and JetBrains Mono from Google Fonts. `dashboard/src/styles.css` holds the brand colors and surfaces as CSS variables, with light and dark mode from the system setting, rounded panels with no outlines, and the status and decision colors from assumption 14.
- `dashboard/src/api.ts`: typed fetch functions and types for the API's responses.
- `dashboard/src/money.ts`: `toCents("1250.00")` gives `125000` without floats, and `formatCents(125000)` gives `$1,250.00`.
- `dashboard/src/App.tsx`: a header with the UnderCover name, links to Queue and Instructions, and hash routing (`#/`, `#/claims/CLM-1001`, `#/instructions`), with no router library.
- `dashboard/src/QueuePage.tsx`: a count of claims in each status, then a table of every claim: id, customer, type, submitted, amount claimed, a status badge, and the decision and payout once decided. Each row opens the claim. It polls every 3 seconds.
- The end-to-end setup from assumption 13: `playwright.config.ts` starts the backend on port 8001 with `UNDERCOVER_DB=e2e/test-results/e2e.db` after `uv run -m backend.seed`, and the dashboard on port 5174; `dashboard/vite.config.ts` reads the backend's address from `BACKEND_URL`, defaulting to port 8000. The health test is replaced.

**Why this way.** Hash routing and polling need no new libraries for three pages and one live view. Converting amounts to cents at the edge of `api.ts` means every component works in whole cents.

**Success criteria**

- [ ] `vitest` passes with statement coverage of at least 80%, with tests for `toCents` and `formatCents` (including `"1250"`, `"1250.5"` and `"0.00"`), the queue's counts and rows, and the routing.
- [ ] `e2e/queue.spec.ts` passes: it puts claims into each of the four statuses through the API, and the queue shows 25 rows, the right counts and the right badge on each of those claims.
- [ ] With `npm run dev` running, the Playwright MCP server at `http://localhost:5173` shows the queue with 25 waiting claims in the brand's fonts and colors, in light and dark mode, and clicking a row goes to `#/claims/<id>`.
- [ ] `npm run check:ts` passes.

## Phase 5: the claim page, the live steps and the instructions

**What it builds.** The rest of what the team needs to see.

- `dashboard/src/ClaimPage.tsx`: the claim in full: its status, summary, story, dates and place, the items with their amounts and the total, and each document's text; the policy's plan, add-ons, trip dates and travelers; the customer's name and earlier claims. When decided: the decision, the payout, the explanation and the policy section. The payment's state: paid with the amount, or "Payment blocked: waiting for a handler's sign-off" for a claim over the limit.
- The agent's steps on the same page, in order, each with its kind and text. While the claim is in progress the page polls every 2 seconds, so the team watches the steps arrive.
- `dashboard/src/InstructionsPage.tsx`: the agent's instructions from `GET /api/instructions`, as read-only text.

**Why this way.** One page per claim puts the evidence, the decision and the agent's working side by side, which is how a handler would check the agent's work.

**Success criteria**

- [ ] `vitest` passes with statement coverage of at least 80%, with tests for a waiting claim, a claim in progress with steps, a decided and paid claim, a declined claim, a claim waiting for sign-off, and the instructions page.
- [ ] `e2e/claim.spec.ts` passes: through the API it puts one claim in progress with steps, one decided and paid, and one approved over the limit with its payment refused; the pages show the steps, the decision with its explanation and section, the paid amount, and the blocked payment. `e2e/instructions.spec.ts` shows the instructions.
- [ ] With `npm run dev` running, the Playwright MCP server shows CLM-1001's page with its story, items and documents, and the instructions page shows the text of `backend/instructions.md`.
- [ ] `npm run check:ts` and `npm run e2e` pass.

## Phase 6: the whole pilot, by hand, and the hand-over

**What it builds.** No new features: a run of the whole pilot with a real model, and the documents brought up to date.

- `docs/STATUS.md`: what's built, how to start it (`npm run dev`), how to run the agent on the queue or one claim, how to reset the database, and what is left for later (sign-off from the screens, the claims manual, scoring against `data/evals/`).

**Success criteria**

- [ ] With `npm run dev` running, `$env:MODEL_NAME="openrouter/free"; uv run -m agent CLM-1001` runs while the Playwright MCP server watches `#/claims/CLM-1001`: the claim shows in progress, the steps appear as the agent works, and the page ends with the decision, the explanation and the section. I report what it decided.
- [ ] The queue page shows CLM-1001's new status and decision without a reload.
- [ ] `docs/STATUS.md` is up to date, and every criterion in this plan is ticked.
- [ ] `npm run check` passes: ruff, pyright and pytest with at least 80% coverage, ESLint, Prettier, tsc and vitest with at least 80% coverage, and every Playwright test.
