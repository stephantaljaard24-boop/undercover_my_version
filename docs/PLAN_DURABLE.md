# Plan: approvals that wait, and work that survives a restart

This build brings the payout rules and Langfuse tracing into the product, moves the backend to Supabase, and turns the claim agent into a LangGraph graph that saves its progress, pauses for a handler's sign-off and carries on after the sign-off or after a restart. It works from `docs/DURABLE.md`, in six phases and a review, each building on the last.

SIDENOTE (from the brief): For consistency with the course, please read `labs/week2day3.ipynb` and build the solution in the same style as the lab. Where the lab and this brief differ, follow the brief. Include this sidenote in your plan too.

I read `labs/week2day3.ipynb`, and `labs/week2day1.ipynb` and `labs/week2day1_payout.py` that the brief points to. The graph follows the lab: a `TypedDict` state with `add_messages`, an `agent` node and a `tools` node in a loop, a `decide` node that turns the work into a structured decision, an `approval` node that calls `interrupt()`, a `pay` node, two conditional edges, `PostgresSaver` with `durability="sync"`, and a thread id for each claim. Where the brief or the product's standards differ from the lab, I follow them:

| The lab | The product |
|---|---|
| Amounts are floats | Amounts are `Decimal` in Python and dollar strings over the API (`CODE_STANDARDS` 7) |
| The graph writes the payment into its own `payments` table | The graph pays through the backend, and the backend decides whether the payment is allowed |
| The graph compares the payout with `APPROVAL_LIMIT` | The graph never applies the limit: it asks the backend whether the claim needs a sign-off |
| One global psycopg connection, in the `lab` schema | A connection for each piece of work, in the `undercover` schema, with at most 4 connections in each process |
| The policy wording sits in the system prompt | The agent reads sections through its tools, as it does today |
| A handler can approve or reject | A handler can only sign off (rejecting comes later) |
| The checkpointer is in a notebook | The same `PostgresSaver`, in `agent/harness/checkpoints.py` |

## Open questions and assumptions

1. **Plan file name.** `docs/PROCESS.md` and the brief both put the plan in `docs/PLAN_DURABLE.md`, so I wrote it there, not in `docs/DURABLE.md`.
2. **An approval stays in progress until it is paid.** Today a payout within the limit makes the claim `decided` the moment it is recorded. The brief makes paying a step of the graph and says the claim shows as in progress between the sign-off and the payment. So an approval within the limit stays `in_progress` until the payment is made, then becomes `decided`. A decline or a referral is `decided` at once. A payout over the limit is `awaiting_sign_off`, then `in_progress` after the sign-off, then `decided`. That also gives "carry on" something to find: every claim with agent work left is `in_progress`.
3. **A claim with a decision is never sent back to the queue.** The backend refuses to fail a claim that has a decision (409). If the agent hits an error after the decision, the claim stays in progress on its thread and the next run carries on from its last step, which is only the payment. That keeps "decided once" true and it doesn't count as an attempt. An error before a decision still goes back to `waiting` and starts afresh on a new thread, and the second one is left for a handler, as today.
4. **The thread id belongs to the backend.** `start_claim` creates `CLM-1003-ab12cd34` (the claim id and 8 random hex digits), stores it on the claim and returns it. A restart finds the same thread through the claim, a fresh attempt gets a new one, and a reseed can never collide with an old checkpoint. The id is opaque to the backend.
5. **The Langfuse session is the thread id**, so it is named after the claim and its thread, and the work before and after a pause lands in one session. A fresh attempt is a new thread and so a new session. Each trace also carries the claim id as a tag, so every attempt on a claim can be found together.
6. **"Repeat" means the same verdict and payout.** A second decision with the same verdict and payout on a claim that has one returns the claim unchanged, and the first explanation stays. A different verdict or payout gets 409. A second payment of the paid amount returns the claim, and any other amount gets 409.
7. **No sign-in, so a sign-off names a handler from a list.** `GET /api/handlers` serves the name, role and id from `data/handlers.json` (not the emails). The dashboard asks which handler is signing off. The backend refuses a handler who is unknown or not allowed to approve over the limit. The first sign-off on a claim stands, and a second one returns the claim unchanged.
8. **The payment carries the sign-off.** The sign-off is stored in its own `sign_offs` table (claim, handler, time, in UTC). A claim and its payment show `signed_off_by` and `signed_off_at` from it.
9. **No optional inputs in the payout operation.** The brief's API rule means the lab's defaults (`quantity`, `nights`, `hours`, `paid_by_others`) become required fields. The tool's description tells the model what to pass when a field doesn't apply (`1`, `0`, `0` and `"0.00"`).
10. **The payout operation belongs to a claim**: `POST /api/claims/{claim_id}/payout-calculation`. The policy comes from the claim, so the model can't pass the wrong one. It calculates and stores nothing. It reads the limit from `data/company.json` through `rules.approval_limit()`, the one place the limit is read.
11. **Retries and the call limit move into the graph.** The two retry middlewares become a LangGraph `RetryPolicy` on the model nodes. The model-call limit of 30 becomes a counter in the state that the `agent` and `decide` nodes add to, and the graph raises an error when the next call would be the 31st. The queue agent keeps `create_agent` and its middleware.
12. **The checkpointer is opened for each piece of work**, not once for the life of the process. The session pooler drops idle connections, so a service that holds one for hours would break. Each run of a claim, each resume and each start-up opens one connection, runs `setup()` (which does nothing after the first time and rebuilds the tables after a reseed) and closes it. Tests use `InMemorySaver`, and a restart is a new graph over the same saver. The agent refuses to start without `DATABASE_URL`.
13. **Connections.** Backend: a pool of 2 with 2 more allowed, so 4 at most. The agent: 1 at a time in the command line process, and 1 at a time in the service. Together about 6 of the 15, with room for the Supabase MCP.
14. **A stopped run is finished by the next run.** The backend keeps which claims a run has started (a new `run_claims` table and `started` on the run). The next `uv run -m agent` finds the latest run if it isn't finished and continues it: same run id, same cap, the to-do list it left, and a fresh queue agent that is told which claims were started. Claims it carries on first (stopped or signed off while the agent was away) don't use up a cap, because they were already started. One run at a time is assumed, as in the pilot.
15. **The command line with a named claim** (`uv run -m agent CLM-1001`) carries on that claim if it is in progress, and starts it if it is waiting. It doesn't carry on others.
16. **The service answers at once and works afterwards.** `POST /api/claims/{claim_id}/resume` returns 202 and resumes in the background, and only when the claim's thread is paused at the sign-off, so it never runs a thread the command line is working on. The window where a handler signs off just before the graph reaches its pause is closed on the other side: after a graph pauses, the run checks the backend and carries on if the sign-off is already there.
17. **The service is a second entry point.** `agent/service.py` only wires a FastAPI app, one route and the work it calls, and nothing imports it. `docs/CODE_STANDARDS.md` already allows an entry point, so I change the layout test, not the standard. Tell me if you want a sentence added to the standard.
18. **The old database file.** `backend/undercover.db` has the old schema. After this build, run `uv run -m backend.seed` once. Supabase is seeded with `npm run seed`, which passes `.env`.
19. **Supabase's advisor flags five tables in the `lab` schema with row level security off.** They are the course lab's tables, not the product's, and I won't touch them. The product's tables are in `undercover`, which Supabase's API doesn't expose by default, so I'm not adding policies. You may want to turn it on for the lab tables yourself.
20. **Commits.** The working tree has your staged `docs/HARNESS.md` and edited notebooks. I commit only the files each phase changes, by path, so those stay as they are.
21. **Not built:** rejecting a payout, a tracing session for the queue agent, checking that the recorded payout equals the calculated one, and anything for a later day.

## Layout

Backend (`backend/`):

| Module | Its one job | Imports | Why |
|---|---|---|---|
| `payout.py` (new) | Works out a payout from a policy, a benefit and the claim's lines | `data`, `models`, `rules` | Business rules the routes and the store shouldn't hold. `rules.py` already holds the status rules, and `payout.py` is long enough to stand alone |
| `schema.py` (new) | The tables, as SQLAlchemy Core definitions, with no queries | `sqlalchemy` | The schema is written once and used by `db.py`, `store.py` and the seed |
| `db.py` (changed) | The engine: Supabase when `DATABASE_URL` is set, else SQLite; the `undercover` schema; the pool limit; resetting the schema | `schema` | The one place that knows which database it is |
| `store.py` (changed) | All the queries, as Core statements, each written once for both databases | `schema`, `models` | Stays the only place for queries. It must stay under 300 lines; if it can't, I stop and ask |
| `rules.py` (changed) | The status, sign-off, repeat and payment rules | `data`, `models` | Adds the sign-off rule and the repeat rule, next to the rules that exist |
| `agent_client.py` (new) | Tells the agent's service that a claim was signed off, and shrugs if it can't be reached | `httpx` | The only place that knows the service's address, which is the mirror of the agent's `backend.py` |
| `routes/claims.py`, `routes/runs.py`, `routes/records.py` (changed) | The new and changed operations: sign-off, payout calculation, adding a claim to a run, handlers | `rules`, `store`, `payout`, `agent_client` | Routes stay by resource |
| `models.py`, `seed.py`, `main.py` (changed) | New shapes; seed through the engine; start-up that seeds when the tables are missing | | |

Agent (`agent/`):

| Module | Its one job | Imports | Why |
|---|---|---|---|
| `harness/checkpoints.py` (new) | Opens a `PostgresSaver` on the `undercover` schema, set up and closed after use | `psycopg`, `langgraph` | Any graph needs a durable saver. It knows nothing about claims |
| `harness/tracing.py` (new) | The Langfuse callbacks and session for a run, nothing when the keys are missing, and the flush | `langfuse` | Tracing for any agent |
| `harness/graphs.py` (new) | The retry policy and the model-call count for a hand-written graph | `langgraph` | Takes the place of the middleware for graphs, beside `agents.py` which keeps it for `create_agent` |
| `harness/steps.py` (changed) | Runs an agent or graph on an input or a resume, hands each step on, and reports whether it paused | | Today it only starts agents; resuming needs the input to be anything |
| `undercover/claim_graph.py` (new) | The claim graph: state, nodes, edges | `harness`, `backend`, `tools` | The shape of the work on one claim |
| `undercover/claim_agent.py` (rewritten) | Working a claim and carrying one on: start, run the graph, put right a failure | `claim_graph`, `harness` | Same job as today, on a graph |
| `undercover/queue_agent.py` (changed) | The run: continue a stopped run, carry on stopped claims, then work the queue | | |
| `undercover/tools.py`, `undercover/backend.py` (changed) | The claim tools lose `record_decision` and `pay_claim` and gain `calculate_payout`; the client gains the new calls and their models | | The path to each new call is still written only in `backend.py` |
| `service.py` (new) | The entry point for sign-offs: a FastAPI app with a health check and the resume route | `undercover`, `harness` | The cloud shape of the agent |
| `__main__.py` (changed) | The command-line entry point | | |

The layout tests change to match: the service is an entry point nobody imports, the harness still imports nothing from the product, the backend's query code is only in `store.py`, `db.py` and `schema.py`, and the agent's address appears only in `backend/agent_client.py` and the route in `agent/service.py`.

Dashboard: `SignOffPanel.tsx` (new, so `ClaimPage.tsx` stays small), plus changes to `api.ts`, `ClaimPage.tsx` and `labels.ts`. End-to-end: `e2e/stand-in-agent.mjs` (new), `e2e/signoff.spec.ts` (new), and changes to `e2e/support.ts` and `playwright.config.ts`.

## Phase 1: the payout rules and tracing

**What it builds.** The two things the brief says to bring in first, so everything after runs on the better agent and can be seen.

*The payout rules.*
- `backend/payout.py`: `labs/week2day1_payout.py` moved into the backend with `Decimal` in place of floats, `None` for "no limit" in place of infinity, and the plan data read through `data.load_json`. `needs_sign_off` is `payout > rules.approval_limit()`; the constant `APPROVAL_LIMIT = 1000.0` is not copied.
- Models in `models.py`: `PayoutLine` (all fields required), `PayoutRequest` (`benefit`, `lines`, `paid_by_others`) and `PayoutCalculation` (`calculation`, `payout`, `needs_sign_off`).
- `POST /api/claims/{claim_id}/payout-calculation`, `operation_id` `calculate_payout`, in `routes/claims.py`.
- The agent: `Backend.calculate_payout`, typed models for the answer, and a `calculate_payout` tool in `agent/undercover/tools.py` with the lab's docstring. A refusal (an unknown claim, a bad line) goes back to the model as text.
- `backend/instructions/claim.md` gains a goal-style line: the payout on an approval comes from UnderCover's payout rules, not from the agent's own sums. No tool name, no order, under 400 words.

*Tracing.*
- `agent/harness/tracing.py` builds the Langfuse `CallbackHandler` and a `config` carrying the session id and a tag, and flushes when the work is done. With no Langfuse keys in the environment it adds nothing, so tests never reach the network.
- `run_agent` passes that config. For now the thread id the helper already makes (`CLM-1003-ab12cd34`) is the session id; Phase 3 and Phase 4 move it to the backend.

**Why this way.** The payout rules are fixed business logic, so they are code in the backend (the one place that knows the limit), and a tool lets the model choose which lines count while the arithmetic stays exact. Tracing goes in at the same time because it is how I and you check the payout tool is used, and the harness version is generic, so the graph in Phase 4 only has to pass the same config.

**Success criteria**

- [x] `uv run pytest -q backend` passes, with tests for the payout operation, with expected values I work out by hand from `data/plans.json` and write next to each test:
  - [x] An unknown claim gives 404; a line missing a field gives 422.
  - [x] A per-item limit, the electronics add-on limit and a quantity of three each limit a line as the lab says.
  - [x] Cash is limited to $100 in all, hotel nights to $350 per room-night (rooms are half the travelers, rounded up) and meals without receipts to $35 per traveler per day.
  - [x] What others paid is taken off, the deductible applies only to the benefits in `deductible_applies_to`, the payout is capped at the benefit maximum (and at the trip cost for trip cancellation and interruption), and it never goes below zero.
  - [x] `needs_sign_off` is false at `1000.00` and true at `1000.01`, and follows a limit changed in a test.
- [x] `uv run pytest -q agent` passes, with tests that: the `calculate_payout` tool returns the calculation as text and a refusal as text; the tracing config has the thread id as its session and the claim id as a tag; it adds no callbacks when the keys are missing.
- [x] `backend/tests/openapi.json` is saved with the command the failing test prints, and the diff shows one new operation and nothing else.
- [x] `uv run pytest -q backend/tests/test_instructions.py` passes.
- [x] `npm run check:python` passes.
- [x] By hand, with the backend on a freshly seeded database and the default model: `uv run -m agent CLM-1008` finishes, its steps on `GET /api/claims/CLM-1008/steps` include a `calculate_payout` call, and Langfuse's API lists a trace for that session with the call in it. Langfuse Cloud removed its traces endpoint on 2026-11-16, so the check reads the v2 observations endpoint (`get_client().api.observations.get_many(fields="core,basic", ...)`) and groups by `trace_id` and `session_id`. I report what the agent decided.

  Result: `uv run -m agent CLM-1008` approved $2,240.00 with the payment waiting for sign-off, after a `calculate_payout` call. Langfuse showed session `CLM-1008-f9adf50c` with one trace that holds the call.

## Phase 2: our records on Supabase

**What it builds.** The backend on SQLAlchemy Core, on SQLite or Supabase, with no change in behaviour.

- `sqlalchemy` joins the root `pyproject.toml`'s dependencies (it is only in a group today). `uv lock` already knows version 2.1.3.
- `backend/schema.py`: the eight tables from the old `SCHEMA` string, as Core `Table`s on one `MetaData`, with money and JSON kept as text, as they are.
- `backend/db.py`: `engine()` is cached by URL. With `DATABASE_URL` it makes a `postgresql+psycopg://` engine with `connect_args={"options": "-c search_path=undercover"}`, `pool_size=2`, `max_overflow=2` and `pool_pre_ping=True`. Without it, a SQLite engine on `UNDERCOVER_DB`. `reset_schema()` drops and recreates the `undercover` schema on Postgres (which also clears the checkpointer's tables, and `setup()` brings them back) and drops and creates the tables on SQLite.
- `backend/store.py`: each SQL string becomes a Core statement, one version for both databases. `INSERT OR IGNORE` becomes an insert that selects only when the row isn't there. A write ends with `conn.commit()`.
- `backend/routes/dependencies.py` yields a Core connection; `seed.py` and `main.py` use the engine, and start-up seeds when the `claims` table is missing.
- `package.json`: `dev:backend` runs `uv run --env-file .env -m uvicorn ...` so `.env` reaches the backend; a new `seed` script runs `uv run --env-file .env -m backend.seed`. `playwright.config.ts` sets `DATABASE_URL` to an empty string for the backend it starts, and `conftest.py` removes `DATABASE_URL` for every test.

**Why this way.** Doing the database move before any new behaviour means every existing test is a check on it: if one fails, the move broke it. Core keeps the "one query, written once" rule from `CODE_STANDARDS` 9 while the two databases differ. The `undercover` schema, set by `search_path`, keeps the queries identical, and keeps the product out of the lab's `lab` schema and Supabase's own.

**Success criteria**

- [x] The whole existing `backend` and `agent` suite passes on SQLite with `DATABASE_URL` removed, and `backend/tests/openapi.json` is unchanged and green.
- [x] New tests, with no connection made: a Postgres URL becomes a `postgresql+psycopg` engine URL with the `undercover` search path; the pool allows 4 connections at most; no `DATABASE_URL` gives SQLite on `UNDERCOVER_DB`; an empty `DATABASE_URL` counts as unset.
- [x] `backend/tests/test_layout.py` finds queries only in `store.py`, `db.py` and `schema.py` and now also catches Core (`select(`, `insert(`, `update(`, `delete(`, `.execute(`) anywhere else; `store.py` is under 300 lines.
- [x] `npm run check:python` passes.
- [ ] With `.env` passed, `npm run seed` prints that 25 claims were loaded, and the Supabase MCP server's `list_tables` for the `undercover` schema shows `claims`, `policies`, `customers`, `decisions`, `payments`, `steps`, `reads` and `runs`, with 25 rows in `claims`. Running it a second time works. The `lab` schema's tables have the same row counts as before (3 payments, 23 checkpoints).
- [ ] With `npm run dev` and `.env` in place, `curl.exe -s http://127.0.0.1:8000/api/claims` returns 25 `waiting` claims from Supabase, and with `DATABASE_URL` absent it returns them from SQLite.

*Not yet done: the two live Supabase checks above. From this machine port 5432 to the session pooler times out (443 works), so they are done once the network allows it.*

## Phase 3: a sign-off in the product

**What it builds.** The backend rules and the dashboard for a handler's sign-off, plus the repeat-safe decision and payment, so the agent in Phase 4 has a backend that is ready for it.

*Backend.*
- Statuses and rules (`rules.py`): an approval within the limit stays `in_progress` until paid; a decline or referral is `decided`; a payout over the limit is `awaiting_sign_off`. `pay_claim` moves the claim to `decided`.
- `claims.thread_id`: `start_claim` creates `CLM-1003-ab12cd34` and returns it on the claim.
- `POST /api/claims/{claim_id}/sign-off` (`sign_off_claim`, takes a `handler_id`): the claim must be `awaiting_sign_off` and the handler allowed; it saves a row in `sign_offs` (claim, handler, time), moves the claim to `in_progress`, and after the response is sent calls `agent_client.notify_signed_off`. The sign-off stands if the call fails.
- `GET /api/handlers` (`list_handlers`).
- `pay_claim`: a payout over the limit is refused with 403 unless the claim has a sign-off; a repeat of the paid amount returns the claim; another amount gets 409. A payment shows `signed_off_by` and `signed_off_at`, and the claim shows its `sign_off`. The payment's input model is separate from its output, so the new fields aren't optional inputs.
- `record_decision`: a repeat (the same verdict and payout) returns the claim; a different one gets 409; the repeat check comes before the status check, because the claim is no longer `in_progress` after the first.
- `fail_claim`: refused with 409 when the claim has a decision.
- Runs: `POST /api/runs/{run_id}/claims` (`add_run_claim`) and `started` on the run, for Phase 5.
- `backend/agent_client.py` reads `UNDERCOVER_AGENT` (default `http://127.0.0.1:8002`) and posts to `/api/claims/{claim_id}/resume` with a short timeout; a failure to connect is logged and ignored.
- The existing helper in `agent/` changes only as far as the new statuses need until Phase 4 replaces it.

*Dashboard.*
- `api.ts`: `Handler`, `fetchHandlers`, `signOff`, `sign_off` on the claim, and the payment's `signed_off_by` and `signed_off_at`. Amounts stay whole cents.
- `SignOffPanel.tsx`: for a claim waiting for sign-off, a choice of handler and a "Sign off" button, in the brand's Sea Green. After the sign-off the claim shows as in progress with "Signed off by Dana Whitfield on Nov 20, 2026, 2:03 PM".
- `ClaimPage.tsx`: the payment line shows who signed off and when. The page keeps polling until the claim is decided or left for a handler, so it sees the agent pay.
- `e2e`: `stand-in-agent.mjs` is a tiny server on port 8003 that records the calls it gets and lists them; `playwright.config.ts` starts it and runs the e2e backend with `UNDERCOVER_AGENT` pointing at it, so the tests never reach the agent's service.

**Why this way.** All the rules that make "nothing happens twice" and "no payout over the limit without a sign-off" true live in the backend, where they hold whatever the agent does. The sign-off is saved before the agent is told, so a crash or an unreachable agent can't lose it. The dashboard and the backend land together because a sign-off with no way to give it can't be checked.

**Success criteria**

- [x] `uv run pytest -q backend` passes, with tests (a conftest fixture points the notification at a recorder, so no test reaches a real service) that:
  - [x] A decision within the limit leaves the claim `in_progress` until `pay_claim`, which makes it `decided`; a decline and a referral are `decided` at once.
  - [x] A payout of $1,500.00 is `awaiting_sign_off`; paying it gives 403 and records nothing; signing off moves it to `in_progress` and records who and when; paying it then works and the payment shows the handler and the time.
  - [x] A sign-off by an unknown handler, a handler who can't approve over the limit, or on a claim that isn't waiting for one is refused. A second sign-off returns the claim and keeps the first.
  - [x] The sign-off notifies the agent exactly once, after the response, with the claim id; an unreachable agent still leaves the sign-off saved and the response 200.
  - [x] Repeating the same decision returns the claim with one decision stored; a different verdict or payout gets 409. Paying twice records one payment; paying a different amount gets 409.
  - [x] A claim with a decision can't be failed; a claim without one can, and a fresh `start_claim` gives a new `thread_id` while a restart does not change the old one.
  - [x] `started` lists the claims added to a run, in order.
- [x] `backend/tests/openapi.json` is saved; the diff shows the new operations and the changed shapes, and each new operation has an `operation_id`, a one-line docstring and no optional inputs.
- [x] `vitest` passes with at least 80% statement coverage, with tests for the sign-off panel (the handlers, the button, the call it makes), the payment line with and without a sign-off, and the polling rule.
- [x] `e2e/signoff.spec.ts` passes: a claim put into `awaiting_sign_off` through the API shows the panel; choosing a handler and clicking "Sign off" shows "In progress" and the stand-in on port 8003 has received that claim id; paying the claim through the API then shows "Paid $1,500.00" with the handler's name.
- [x] `npm run check` passes.

## Phase 4: the claim graph and its saved progress

**What it builds.** The claim agent as a hand-written LangGraph graph with a Postgres checkpointer, a pause for sign-off, and carrying on.

- `agent/undercover/claim_graph.py`:
  - **State** (`TypedDict`): `messages` (with `add_messages`), `claim_id`, `decision`, `payout`, `explanation`, `policy_section`, `needs_sign_off`, `model_calls`.
  - **Nodes:** `agent` (the model with the claim tools, as in the lab), `tools` (`ToolNode`, so a refusal still goes back as text), `decide` (a structured `ClaimDecision`, as in the lab, with the payout as a dollar string), `record` (records the decision through the backend and sets `needs_sign_off` from the status the backend returns, so the graph never compares with the limit; it adds a short reply saying what was recorded), `sign_off` (`interrupt()` with the claim, the payout and the explanation) and `pay` (pays the recorded payout through the backend and adds a reply saying so).
  - **Edges:** `START → agent`; `agent → tools` while the model asks for tools, else `decide`; `tools → agent`; `decide → record`; after `record`: a decline or referral ends, an approval that needs a sign-off goes to `sign_off`, any other approval goes to `pay`; `sign_off → pay → END`.
  - Both the `agent` and `decide` nodes raise a clear error when the next model call would be the 31st; the model nodes have the retry policy. Both come from `harness/graphs.py`.
  - `decide` and `record` are separate nodes on purpose: the decision is saved in the state before it goes to the backend, so a crash between them replays the same decision, which the backend treats as a repeat.
- `agent/undercover/tools.py`: `get_claim`, `get_policy`, `get_customer`, `get_contents`, `read_section`, `calculate_payout`. `record_decision` and `pay_claim` go, as the brief says.
- `agent/harness/checkpoints.py`, `graphs.py` and `steps.py` as in the layout. `steps.py` turns the agent and tools messages into steps as today, takes the `__interrupt__` chunk as "paused" (not as a step), and runs with `durability="sync"`.
- `agent/undercover/claim_agent.py`:
  - `work_claim`: start the claim (which returns the thread id), run the graph on a new thread with the Langfuse session set to the thread id, then:
    - **paused:** the claim is `awaiting_sign_off`: report "payment waiting for sign-off". If the backend already shows the sign-off, carry on at once.
    - **finished:** report the decision and the payment.
    - **an error:** if the claim has no decision, `fail_claim` (it goes back to `waiting`, a second failure is left for a handler); if it has one, leave it in progress and say the next run will carry on.
  - `carry_on`: look at the thread. No saved step yet: start the graph on the same thread. Paused at the sign-off: resume with the handler's name if the backend has the sign-off, else leave it. Anywhere else: run it on from the last saved step. It never calls `start_claim` or `fail_claim` for a stop, so attempts don't change. It has a "paused only" mode for the service.
  - Ctrl-C and a kill are not caught, so the claim stays in progress on its thread.
- `backend/instructions/claim.md` loses recording and paying as things the agent does: the goal is the decision, its payout, an explanation and a policy section, and the system holds a payout over $1,000 for a handler; the agent isn't told to pay or to retry.

**Why this way.** The graph is the lab's shape, so what you built in the lab is what runs here. Letting the backend say whether a claim needs a sign-off keeps the rule in one place. Saving the state after every step with `durability="sync"` is what makes both a pause that lasts hours and a kill at any point safe, and the repeat-safe decision and payment from Phase 3 are what make replaying a step safe.

**Success criteria**

- [x] `uv run pytest -q agent` passes. The tests use a stub model and an `InMemorySaver`, and none calls a model or Supabase. They cover:
  - [ ] A claim within the limit: the stub reads the claim, calculates, decides; the claim ends `decided` and paid, with one decision, one payment and its steps in order (tool calls, results, the model's reply, the recorded decision and the payment).
  - [ ] A claim over the limit: the run ends with the graph paused at `sign_off`, the claim `awaiting_sign_off`, no payment, and `needs_sign_off` set from the backend's answer. Signing off in the backend and calling `carry_on` pays it once and ends `decided`. Calling `carry_on` again changes nothing.
  - [ ] Signing off before the graph pauses: `work_claim` pauses, sees the sign-off, carries on and pays once.
  - [ ] A stop partway: a stub that raises a `BaseException` on its second call stops the run. A new graph over the same saver, with a stub for the rest, carries on from the last saved step: the same thread id, `attempts` still 0, one decision, no step recorded twice.
  - [ ] An error before the decision: the claim goes back to `waiting` with `attempts` 1, the next `work_claim` makes a new thread, and a second error leaves it `needs_handler`.
  - [ ] An error after the decision leaves the claim in progress with its thread, and `carry_on` pays it.
  - [ ] A replay of `record` and of `pay` (the node run twice on the same state) leaves one decision and one payment.
  - [ ] The model-call limit stops the 31st call with a clear error and counts as an error before the decision; a failing model call is retried.
  - [ ] The state the graph saves has the claim id, the decision and the payout, and the tools no longer include `record_decision` or `pay_claim`.
- [x] `agent/tests/test_layout.py` still shows the harness importing nothing from the product, and that nothing imports `agent.__main__`. `test_instructions.py` passes.
- [x] `npm run check:python` passes.
- [ ] By hand, on Supabase with `npm run seed` first, one claim over the limit (CLM-1008) with the default model: `uv run -m agent CLM-1008` ends paused, `GET /api/claims/CLM-1008` shows `awaiting_sign_off` and the thread id, and the Supabase MCP server's `select thread_id, count(*) from undercover.checkpoints group by 1` shows that thread. Signing off through the backend (`curl.exe`, with the service not running yet) and then `uv run -m agent CLM-1008` again pays it, with the same thread. I report the decision and the payout.

*Not yet done: the live Supabase check above, for the same reason as Phase 2. The graph itself ran with the default model on a local backend and an in-memory saver: `CLM-1008` was approved for $2,240.00, with a `calculate_payout` call, then paused with the payment waiting for sign-off, in Langfuse session `CLM-1008-2da35851`.*

## Phase 5: the agent's service and picking up after a restart

**What it builds.** The service the backend calls after a sign-off, and a run that first carries on what was left.

- `agent/service.py`: a FastAPI app with `GET /api/health` and `POST /api/claims/{claim_id}/resume` (`resume_claim`, one-line docstring, no optional inputs, 202). The route adds the work to the background and returns; the work opens the checkpointer, runs `carry_on` in "paused only" mode, and flushes Langfuse. Resumes run one at a time under a lock. Its start-up builds nothing that holds a connection.
- `agent/__main__.py`: with no claim named, first carry on every claim that is `in_progress` and has a thread (stopped, or signed off while the agent was away), then run the queue. With a named claim, carry it on if it is in progress and start it if it is waiting. It prints one line for each.
- `agent/undercover/queue_agent.py`: `run_queue` looks for the latest run and continues it if it isn't finished (same run id and cap, its to-do list in the first message, the claims it started listed, `Run` rebuilt with them), else starts a new one. `work_claim` adds the claim to the run in the backend before it hands the claim on.
- `package.json`: `dev:agent` runs `uv run --env-file .env -m uvicorn agent.service:app --port 8002`, and `dev` runs the backend, the dashboard and the agent service together. It must work on Windows.

**Why this way.** The backend never waits for the agent, so a handler's click is instant and the sign-off can't be lost; the 202 plus background work gives the "paid within five seconds" the brief wants. Putting "carry on what was left" at the start of every run, and keeping the run's progress in the backend, makes a restart the same as any other start, with nothing to remember. The service can be the cloud shape later: the same code in a container beside the app.

**Success criteria**

- [x] `uv run pytest -q agent` passes, with tests (a test client on the service, a stub model, an `InMemorySaver` and the backend's test client) that:
  - [ ] `POST /api/claims/CLM-1008/resume` on a signed-off claim returns 202 and the claim ends `decided` with one payment; the same call again changes nothing.
  - [ ] The same call on a claim that is still `awaiting_sign_off`, or whose thread isn't paused, does nothing.
  - [ ] `run_queue` carries on a stopped claim and a signed-off claim before it starts new ones, and carried-on claims don't use the cap.
  - [ ] A stopped run (the first process dies after two claims) is continued by the next call: the same run id, the same cap, the already started claims not counted twice, and one summary at the end.
  - [ ] The agent's operation has an `operation_id`, a docstring and no optional inputs.
- [x] `agent/tests/test_layout.py` knows the service as an entry point nobody imports, and checks that the backend's route paths are written in `backend.py` only and the service's route path in `service.py` and `backend/agent_client.py` only.
- [ ] `npm run dev` starts three processes on Windows, and `curl.exe -s http://127.0.0.1:8002/api/health` answers.
- [x] `npm run check:python` and `npm run check` pass.

*Not yet done: `npm run dev` as a whole. `npm run dev:agent` starts the service on Windows and `curl.exe -s http://127.0.0.1:8002/api/health` answers, but the backend started with `.env` connects to Supabase at start-up, which the network doesn't allow yet.*

## Phase 6: the whole thing, live, and the documents

**What it builds.** No new features: a live run on the real model, the checks the brief asks for, and the documents brought up to date.

- `docs/SPEC.md`: the section on working the queue now says a run carries on what was left, that an approval over $1,000 waits for a handler and is paid after the handler signs off on the screens, and that a stopped claim carries on. The "Not for now" line about signing off on the screens goes. The Rules stay as they are.
- `docs/TECH_STACK.md`: SQLAlchemy Core on SQLite or Supabase and the `undercover` schema, the claim agent as a LangGraph graph with the Postgres checkpointer, the agent's service and its address, Langfuse, and the payout rules.
- `docs/PROCESS.md`: `npm run dev` starts three things; `npm run seed` reseeds Supabase; `npm run check` needs no `.env`; and the rule that a live run follows a reseed and is capped at five claims.
- `docs/STATUS.md`: what's built and how to run it, the changed API, the live-run results next to the last hand check, and what's left.

**Success criteria**

- [x] With `.env` moved out of the way (renamed, then put back), `npm run check` is green: no Supabase, Langfuse or OpenRouter is needed. (Checked: `.env` renamed, `npm run check` green, `.env` put back.)
- [ ] `npm run seed`, then `npm run dev`, then `uv run -m agent --limit 5` on the default model works five claims. I report each decision next to the last hand check in `docs/STATUS.md` (CLM-1001 $420.00, CLM-1008 and CLM-1011 waiting for sign-off, CLM-1018 referred, CLM-1010 declined), and say why if one differs, without opening `data/evals/`.
- [ ] A claim over the limit shows `awaiting_sign_off` with the payout blocked. Through the Playwright MCP server at `http://localhost:5173`, choosing a handler and clicking "Sign off" shows "Paid" with the handler and the time within five seconds, with the run's command line finished and the agent's service doing the work.
- [ ] Kill the command line process (`taskkill /T /F` on the whole tree) after a claim's first steps appear, check the claim is `in_progress` with its thread, then run `uv run -m agent --limit 5` again: it carries on with the same thread id, `attempts` is unchanged, and the claim has one decision. The stopped run is finished by that run, with one summary.
- [ ] While the run is going, the Supabase MCP server's `select count(*) from pg_stat_activity where usename = 'postgres'` shows 12 or fewer, and I note the highest I saw.
- [ ] Through Langfuse's v2 observations API (the traces endpoint is gone), the held claim's session has at least two distinct `trace_id`s, from before and after the sign-off, and the session also shows a trace for each claim in the run.
- [ ] `docs/SPEC.md`, `docs/TECH_STACK.md`, `docs/PROCESS.md` and `docs/STATUS.md` describe the product as it now is, and every criterion in this plan is ticked.

*Not yet done: every live criterion above (the reseed and five-claim run on Supabase, the sign-off on the dashboard, the killed run, the connection count, and the Langfuse sessions before and after the sign-off), and so the last criterion, because it asks for every criterion to be ticked. This machine can't reach Supabase's session pooler on port 5432 (it times out; port 443 works). The documents are updated to describe the product as it now is, and `docs/STATUS.md` says which checks are still to do.*

## Phase 7: review

Read the whole diff as a reviewer would, fix what I'd ask to change, then run `npm run check`. The checks from `docs/CODE_STANDARDS.md`, each with the search or test that shows it:

- [x] **1. Simple.** The graph has the six nodes in the plan and no more; I list every new module and what it does, and cut anything with no use.
- [x] **2. Comments only when necessary.** `rg -n "^\s*#" backend agent --glob "!**/tests/**"` shows only comments that say why.
- [x] **3. Concise, no emojis, no README.** `git status` shows no product README and no change to the root `README.md`; `rg -n "[^\x00-\x7F]" backend agent dashboard/src e2e` finds no emoji.
- [x] **4. Not over-defensive.** I list each `try` and `except` I added; each is for a reason in the brief (an unreachable agent, a failed claim), and the rest are gone.
- [x] **5. uv.** `rg -n "python3" package.json lefthook.yml docs agent backend` finds nothing; every Python script in `package.json` is a `uv run` command.
- [x] **6. TypeScript strict, no `any`.** `rg -n "\bany\b" dashboard/src e2e --glob "*.ts*"` finds none that are types; `tsc` passes.
- [x] **7. Money.** `rg -n "float\(|: float|Float" backend agent` finds nothing that holds an amount; the payout code uses `Decimal`; `dashboard` keeps cents.
- [x] **8. One job per module, named for it, under 300 lines.** The layout tests in `backend` and `agent` pass; I check `store.py`, `claim_graph.py` and `ClaimPage.tsx` by line count.
- [x] **9. Say each thing once.** `rg -n "/api/" agent` finds paths only in `undercover/backend.py` and the service's own route; `rg -n "payout_approval_limit|1000" backend agent` finds the limit read only in `rules.approval_limit()`; `rg -n "UNDERCOVER_AGENT|8002"` finds the address in `agent_client.py` and `package.json` only; the layout tests show queries only in `store.py`, `db.py` and `schema.py`.
- [x] **10. Layers point one way.** `agent/tests/test_layout.py` and `backend/tests/test_layout.py` pass: the harness imports nothing from the product, nothing imports an entry point (`__main__`, `service`), nothing in `agent/` imports `backend`.
- [x] **11. Typed answers.** `rg -n "\.json\(\)|\.text|status_code" agent` finds those only in `backend.py` and the stubs; the tools return models or text built from them.
- [x] **12. Instructions are goals and limits.** `test_instructions.py` passes: no numbered steps, no tool names, under 400 words each; I show the word counts before and after.
- [ ] `git log` shows a commit for each phase with the hook passing, no `--no-verify`, nothing pushed, and no file from outside the build in any commit.
- [ ] `npm run check` passes, and I report the results.
