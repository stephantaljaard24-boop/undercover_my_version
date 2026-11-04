# Plan: cleaning up the harness build for production

This plan answers `docs/HUMAN_REVIEW_HARNESS.md`. It starts with what the review found, confirmed against the code, then the layout I propose for the agent and the backend with the reason for each cut, then the changes to `docs/PROCESS.md` and `docs/CODE_STANDARDS.md`, then nine phases. Nothing has been moved yet. No file other than this plan has been changed.

## 1. Findings

Numbers in the code are from `git ls-files` and a search of the working tree at commit `779273d`.

### The five problems from the review

| # | Verdict | Where, exactly | How it happened |
|---|---|---|---|
| 1 | **Confirmed** | 25 lines in `agent/` (tests aside) hold `/api/`, a host name or both: `main.py` 3, `queue_run.py` 9, `runner.py` 5, `tools.py` 8. 16 distinct paths, and the same path in several places: `/api/claims/{id}` 4 times, `/api/claims` 3, `/api/claims/{id}/payment` 2, `/api/runs/{id}/finish` 2. `BACKEND_URL` is in `tools.py` and the OpenRouter address in `main.py`. The tests write another 32 `/api/...` strings. | The pilot's `tools.py` (commit `df45b27`) already wrote each path as a string beside the call. Each harness phase needed a new call and copied the nearest one. |
| 2 | **Confirmed, with one correction** | The client is not "passed around": `tools.backend()` is called 11 times and each caller opens its own (`tools.py` 4, `main.run` 1, `runner.work_claim` 1, `queue_run` 5). There are 20 direct `client.get/post/put` calls. Handling differs by caller: `reply_of` in the tools, `is_error` in `runner` and `work_claim`, `is_success` in `write_todos`, a bare `.json()` in six places and a bare `.text` in two. | Same cause as 1. The pilot's helper was a function that returns a client, so every caller had to decide what to do with the response. |
| 3 | **Confirmed** | `queue_run.py`, `runner.py` and `main.py`'s `run` all import from `agent/main.py`, and `queue_run.py` and `runner.py` import `reply_of` and `backend` from `agent/tools.py`, so `tools.py` is also a library. `agent/main.py` holds five jobs: the model, the middleware, steps, streaming and the single-claim run. `backend/main.py` is 396 lines: the app, 20 routes, every statement of SQL, the status rules and the approval limit. Repeated SQL: `SELECT claim_id FROM claims WHERE claim_id = ?` 4 times, `SELECT status ...` 3, `SELECT * FROM runs WHERE run_id = ?` 3, `SELECT run_id FROM runs ...` 2. `str(run_id)` turns an integer into a string 4 times to fit `find`. | `backend/main.py` was the one file named in `docs/PLAN.md` and every later phase added routes "to `backend/main.py`": 131 of its lines come from the pilot's records phase, 91 from the workflow phase, 61 from Phase 1 of the harness, 104 from Phase 2. For the agent, `PLAN_HARNESS.md` names `agent/main.py` for Phase 3 and `agent/queue_run.py` for Phase 4, so the plan put each addition in a file before anyone asked what the file was for. |
| 4 | **Confirmed** | The harness parts, all generic: `model()`, `build_agent`, `steps_of`, `stream_steps`, `TodoItem`, the `Run` class with its cap and lock, and the `write_todos` tool. They sit in `agent/main.py` beside `run()`, which says "Decide claim ..." and fetches `/api/instructions/claim`, and in `queue_run.py` beside `list_waiting_claims`, which formats claims. | `PLAN_HARNESS.md` describes the work per feature (the helper, the queue agent), not per kind of code, so each feature's generic and business parts were written together. |
| 5 | **Confirmed** | `claim.md` is 908 words and `queue.md` 466. `claim.md` has a numbered six-step procedure ("1. Read the claim with `get_claim`... 4. Record your decision once... 6. Finish with one sentence"), a second numbered list for the payout, and a checks list. `queue.md` has a numbered seven-step procedure. Both name tools in order. They copy rules that live elsewhere: 90 days (wording section 11, manual section 4, and `claim_filing_window_days` in `data/company.json`), the third claim in 12 months (manual section 9), the payout steps (wording section 10, manual section 6), the deductible, and the $1,000 limit (`payout_approval_limit`). | `PLAN_HARNESS.md` asked for it: Phase 3 says the instructions tell the agent "to read the claim..., read the contents..., decide..., record the decision, then pay", and Phase 4 lists `queue.md` as seven steps. The pilot's instructions were a procedure too, and the plan kept the shape. |

### Others of the same kind

- **N1. Untyped answers.** The agent reads `claim["status"]`, `c['amount_claimed']` and `claim["decision"]["payout"]` from `.json()`, which is `Any`, so pyright cannot catch a wrong key. `describe` in `runner.py` is all dict lookups.
- **N2. The run is finished in two places.** `finish_run` (the tool) and the fallback at the end of `run_queue` both post to `/api/runs/{id}/finish`.
- **N3. `agent/tools.py` says "each one calls a single backend operation"** and also holds the transport (`backend`, `reply_of`, `fetch`).
- **N4. An import-time side effect.** `agent/main.py` runs `load_dotenv(override=True)` on import, so importing the model code changes the environment.
- **N5. Tests are tied to the layout.** `conftest.py` replaces `tools.backend` and `main.RETRY_DELAY` by module path, and the tests assert through 32 literal URLs. Moving a function breaks every test, and a new way to reach the backend would need none of them to change.
- **N6. Backend: rules in more than one place.** The not-in-progress conflict (`Claim X is Y, not in_progress`) is written in `record_decision` and again in `fail_claim`, and in `move` for any other status. The attempts limit is `MAX_ATTEMPTS` in `main.py`, "twice" in `queue.md`, and in `describe`. `json.loads(text, parse_float=Decimal)` is written in `seed.load_json` and in `approval_limit`.
- **N7. Backend: SQL.** `decisions`, `payments`, `policies` and `customers` are inserted with a bare `VALUES (?, ?, ...)` that depends on column order. `list_claims` builds each row with `claim_detail`, which runs four queries per claim (25 claims, polled every 3 seconds) and reads the customers table in full.
- **N8. Backend: `DATA_DIR` lives in `db.py`**, so `documents.py` imports a path from the database module.
- **N9. Backend: the approval limit is read from `data/company.json` on every call** and the file is parsed again each time.
- **N10. Dashboard, small.** The set of statuses is written three times in `api.ts` and `labels.ts` (a union, an array, a label record). `RunPanel` uses `todo.text` as a React key, and the text comes from the model, so two items with the same text collide.

### The backend and the dashboard against the same list

| Part | Verdict | Why |
|---|---|---|
| `backend/main.py` | **Fix** | Everything in one file (problem 3, N6, N7, N9). |
| `backend/models.py` (165 lines) | **Fine** | One job, the shapes of the API. Leave. |
| `backend/documents.py`, `seed.py` | **Fine, small edits** | One job each. They take `DATA_DIR` and `load_json` from a new `data.py` (N6, N8). |
| `backend/db.py` | **Fine, small edit** | Connection and schema. Loses `DATA_DIR`. |
| `dashboard/src/api.ts` (247 lines) | **Mostly fine** | Every path is written once and every answer is typed, and the wire-to-cents conversion is in one place. Only N10 changes. |
| `dashboard/src/ClaimPage.tsx` (264 lines), `QueuePage.tsx` | **Fine** | A page and its panels, 7 small components, each under 50 lines, below the ESLint limit of 500. Splitting would be change for its own sake. `RunPanel` gets a safe key (N10). |
| `labels.ts`, `usePolling.ts`, `InstructionsPage.tsx`, `route.ts`, `App.tsx`, `money.ts` | **Fine** | One job each. |
| `e2e/support.ts` | **Fine** | It must stay independent of the dashboard's code, because it checks the API as a client would. It repeats the status words on purpose. |

### Why every check passed

None of the checks looks at structure.

- **ruff** (`E F W I B SIM UP PL S PT FAST C90 PLR1702`) judges one statement or one function at a time. It has no rule for a repeated string, a file's length, what a module is named, or which module may import which. `C90` allows a complexity of 10, and every function is under that because the mess is between functions.
- **pyright** checks types. `httpx` returns `Any` from `.json()`, so the dict lookups in the agent type-check.
- **pytest and 80% coverage** show that lines run, and the tests run them through the same seams, so a different layout would have passed too.
- **ESLint** has `max-lines` of 500 and `max-lines-per-function` of 200, but the Python side has no counterpart. `backend/main.py` at 396 lines is under even the TypeScript limit.
- **The pre-commit hook** runs the same checks.

### The gaps in the documents

| Document | The gap |
|---|---|
| `PROCESS.md`, Planning | It asks for phases, open questions and success criteria, all about behavior. It never asks where the code goes, so `PLAN_HARNESS.md` named a file for each addition and nobody chose the modules. |
| `PROCESS.md`, Implementing | "Build every phase in order without stopping" has no point where anyone looks at the whole. The only final step is `npm run check`, and the build was a sequence of additions. |
| `PROCESS.md`, Rules | "Add tests with each change" and "Run `npm run check`" say what to run, nothing about reading the diff as a reviewer would. |
| `CODE_STANDARDS.md` | Seven rules, none checkable for structure. "Keep it simple" and "avoid overly defensive code" are true of each function here and push toward the smallest edit, so a duplicate call was simpler than a shared one. There is nothing on repeated literals, where a URL, a query or a rule lives, what a module is named, layers, or the length of a file. |
| `HARNESS.md` (the brief) | It said "build these pieces into our own agent" and "keep it simple", and called for instructions "we can read". It did not say that the harness is a reusable part, nor that instructions should be goals. This is the customer's brief and stays as it is; the fix belongs in the documents the build works to. |
| `PLAN_HARNESS.md` | Phase 3 and 4 specify the instructions as a procedure. The agent that wrote the plan took the pilot's procedure as the style. |
| `lefthook.yml` / `npm run check` | No layout check exists to fail. |

## 2. Open questions and assumptions

1. **Entry points.** `agent/__main__.py` is the agent's only entry point. `backend/main.py` stays as the backend's thin entry point (the app, the lifespan, the routers, health), because `uvicorn backend.main:app`, the e2e config and the AWS Lambda work in Week 3 all name it. Nothing in the product imports it; the tests do, to get the app.
2. **The harness keeps the brief's four to-do states**, including `left_for_handler`, because `HARNESS.md` asks for exactly those and renaming the fourth would change the API and the dashboard. It is the one business word in the harness. If you would rather have a neutral name (such as `blocked`), say so and it becomes a rename across the API, the dashboard and the tests.
3. **`HTTPException` in the backend's store and rules.** The store and the rules raise it directly. Domain exceptions with a handler would be purer but are more code to read, and the standards say simple.
4. **A saved copy of the OpenAPI document** (`backend/tests/openapi.json`) with a test that compares it to the live one, so "unchanged" is a failing check in every phase. Later builds that add routes regenerate it on purpose. It is the cheapest check that fits "the OpenAPI document should come out the same".
5. **Two new checks, both pytest.** Neither lowers, turns off or excludes anything. (a) A layout test for the agent and one for the backend that read each source file's imports with `ast`. (b) A line limit of 300 for Python source files, the Python counterpart of the TypeScript limit (500). I picked 300 because after the split no file comes near it and it would have caught `backend/main.py`. ESLint stays at 500.
6. **Refusals.** Tool refusals still reach the model as text, with the same words (`Refused (404): ...`). The backend client raises one `Refused` error, a LangChain `ToolException`, and the tools are built with `handle_tool_error=True`, so LangChain turns it into the tool's text. If that does not behave as the tests need, a 6-line decorator does the same.
7. **The agent talks to the backend only through the HTTP API and never imports `backend`**, as `TECH_STACK.md` says. The layout test checks it. The agent's typed answers are small models that name only the fields it reads and ignore the rest.
8. **Live run.** After the last code phase: reseed, restart, a run capped at five claims on the default model, a look with the Playwright MCP server, and the decisions compared with `docs/STATUS.md`. `data/evals/` stays closed. Instruction wording is written from `data/policy_wording.md`, `data/claims_manual.md` and `data/company.json` only.
9. **No new feature, route, `operation_id`, screen or dependency.** The tests keep their meaning; their imports, fixtures and URL strings change.

## 3. The proposed layout

### The agent

```
agent/
  __main__.py          entry point: reads the arguments, loads .env, runs one claim or the queue
  harness/             runs any agent; knows nothing about claims
    model.py           the chat model from MODEL_NAME on OpenRouter (the OpenRouter address lives here)
    agents.py          build_agent: create_agent plus retry and call-limit middleware
    steps.py           messages to (kind, text) steps; run_agent streams an agent and reports each step
    todos.py           TodoItem and the write_todos tool, which saves through a function it is given
    limits.py          Run: the cap on items started, the lock, and the check for items missed
  undercover/          the business: claims, the backend and the two agents
    backend.py         the only code that knows the backend's address, paths and status codes
    tools.py           the claim helper's seven tools, built on a Backend
    claim_agent.py     work_claim: start a claim, run the helper, recover from a failure, report a line
    queue_agent.py     the queue agent's four tools and run_queue
  tests/
```

| Cut | Reason |
|---|---|
| `harness/` and `undercover/` | The harness is what would run any agent. Putting it in its own folder, with a test that it imports nothing from `undercover`, makes the split a failing check and not a habit. |
| `harness/model.py` apart from `agents.py` | Which model to use is configuration (a name, a key, an address). How to build an agent around any model is not. A test builds agents with stubs and never touches `model.py`. |
| `harness/steps.py` | Turning messages into steps and streaming them is one job, and `run_agent` replaces the loop that `run()` and `run_queue()` each wrote. |
| `harness/todos.py` | The list tool is generic: items with a status, saved by a function. The queue agent supplies the function that saves to the backend. |
| `harness/limits.py` | The cap, the lock and "which items were missed" apply to any queue of work. It gets ids and answers; it never sees a claim. |
| `undercover/backend.py` | One class, `Backend`, holds an `httpx` client, every path and the handling of a refusal. Callers ask for a claim, a policy, a decision, a run and get typed values or text. How it is reached can change in this file alone. |
| `undercover/tools.py` | The seven tools the helper gets. They are a factory taking a `Backend`, so a test passes a `Backend` over the in-process app and nothing is patched by module path. |
| `undercover/claim_agent.py` (was `runner.py`, and `run()` from `main.py`) | What happens to a claim when it is worked and when it fails: start it, run the helper, record the steps, fail it, pay once after a failure, say it in a line. It uses `harness.run_agent` for the running. |
| `undercover/queue_agent.py` (was `queue_run.py`) | The queue agent's tools and run. Finishing the run is one function used by the tool and the fallback. |
| No `main`, `utils`, `helpers`, `runner` | Every module is named for what it does. |

Dependencies point one way: `__main__` → `undercover` → `harness`. `harness` imports nothing from `undercover`, `__main__` or `backend`. `undercover` imports nothing from `__main__` or `backend`. Tests may import anything.

### The backend

```
backend/
  main.py              entry point: the app, the lifespan, the routers, health
  routes/
    claims.py          list, get, start, steps, decision, payment, fail
    records.py         policies and customers
    documents.py       contents, reads, the two sets of instructions
    runs.py            start, current, to-do list, finish
    dependencies.py    the database connection a route asks for
  store.py             all SQL: claims, steps, decisions, payments, reads, runs
  rules.py             the status rules, the attempts limit and the approval limit
  data.py              DATA_DIR, load_json, and the one place amounts are parsed as Decimal
  db.py                connection and schema (loses DATA_DIR)
  documents.py         the wording and the manual by section (unchanged)
  models.py            the shapes of the API (unchanged)
  seed.py              loads the database (uses data.py)
  instructions/        claim.md, queue.md
  tests/
```

| Cut | Reason |
|---|---|
| `routes/` by resource | A route is a short function that asks the store and the rules and returns a model. Grouping by what the route serves lets a reader find "everything about runs" in one place of about 40 lines. |
| `store.py` | One module holds every statement of SQL, written once: `claim_row`, `require_claim`, `set_status`, `add_decision`, `run_row` and the rest. Insert statements name their columns. `list_claims` is one query. `run_id` stays an integer. A test fails if SQL appears anywhere else. |
| `rules.py` | The status moves, the attempts limit and the approval limit, each written once. `record_decision` and `fail_claim` use one `require_status`. The limit is read through `data.py`. |
| `data.py` | `DATA_DIR` and `load_json` (keeping `Decimal`) are used by `seed`, `documents` and `rules`. They do not belong to the database module. |
| `main.py` kept | See assumption 1. |

### The dashboard

Unchanged apart from N10: `STATUSES` becomes the single list that `Status` is derived from, and `RunPanel` keys its items by position, which is safe because the list is replaced whole.

## 4. How the documents change

Each rule is stated so an agent can check it, and where the tooling can check it, a test does. Neither document grows by more than a dozen lines.

**`docs/PROCESS.md`**

| Gap | Change | Why it holds |
|---|---|---|
| Planning is about behavior | Planning adds: "Put a 'Layout' section after the open questions: each module the work adds or changes, its one job, what imports what, and the reason for each cut. Name a module for its job, never for the feature that added it." | A plan without a layout section is incomplete by the document's own list, and the reviewer reads it before code moves. |
| No look at the whole | Planning adds: "End every plan with a review phase. Its criteria are the checks in `docs/CODE_STANDARDS.md`, each with the search or test that shows it." Implementing adds step 5: "Read the whole diff as a reviewer would before the last commit, and fix what you would ask to change." | The review phase has checkboxes that have to be ticked with evidence, like every other phase. |
| Checks run but do not read the code | Rules adds: "Before you add a call, query, path or constant, search for it. If it exists, use it. If it is written in a second place, move both to one." | It is a step with a verb (search) and a result an agent can show. |
| Nothing fails on structure | Rules adds: "`npm run check` includes the layout tests, which fail on a repeated SQL or backend path, on an import that points the wrong way, and on a source file over 300 lines." | The tests are in `pytest`, so the pre-commit hook and `npm run check` run them. |

**`docs/CODE_STANDARDS.md`** (new rules 8 to 12, short)

8. **One job per module, named for it.** No `main`, `utils`, `helpers` or `runner`, except an entry point, which only wires things up and which nothing imports. A Python source file stays under 300 lines. *(layout test)*
9. **Say each thing once.** A URL path, host name, SQL statement, status rule or constant is written in one place and used from there. The agent reaches the backend only through its client module, and the backend's SQL lives only in the store. *(layout test)*
10. **Layers point one way.** Entry point, then the product, then the harness; routes, then rules and store, then the database. The harness knows nothing about the business. Nothing in `agent/` imports `backend`. *(layout test)*
11. **Callers get typed answers.** Code outside the client never sees a URL, a response object or a status code. Answers are models, not dicts.
12. **Instructions are goals and limits.** Who the agent is, what it is to achieve, the rules it must not break, how to tell it is done, what to report. No numbered steps and no tool order. Point at the wording and the manual and do not copy their rules. Keep each file under 400 words. *(instruction test)*

Gap by gap, in the order of the table in section 1:

| Gap | Closed by |
|---|---|
| PROCESS planning has no layout | the Layout section in PROCESS Planning |
| PROCESS implementing has no look at the whole | the review phase and step 5 |
| PROCESS rules say what to run, not what to read | search before you add |
| CODE_STANDARDS cannot be checked for structure | rules 8 to 12, and the tests behind them |
| Instructions as scripts | rule 12 and its test |
| `PLAN_HARNESS.md` | stays as the record of that build; this plan is the correction |
| `HARNESS.md` | stays as the customer's brief |
| No layout check | `test_layout.py` in `agent/tests` and `backend/tests` |

I think it holds because every rule has a command or a test that fails, the plan has to name the modules before the code is written, and a review phase can't be skipped without an unticked box. It still depends on the plan being honest; a test can't tell a good module name from a bad one beyond the names it forbids.

## 5. Phases

The tests stay green at the end of every phase, and the OpenAPI snapshot is compared in every phase that touches the backend. Each phase ends with its criteria ticked here, `docs/STATUS.md` updated if it changed what the product is, and a commit that the pre-commit hook has checked.

### Phase 1: the backend's data, rules and SQL, each in one place

**What it builds.** The safety net, then `data.py`, `rules.py` and `store.py`. The routes stay in `main.py` for now, calling them.

- Save `app.openapi()` as `backend/tests/openapi.json` before any code moves, with `test_openapi.py` comparing it.
- `data.py` (`DATA_DIR`, `load_json`), used by `seed.py`, `documents.py` and `rules.py`. `db.py` loses `DATA_DIR`.
- `store.py` with every statement of SQL, columns named in each insert, integer run ids, and a single query behind `list_claims`.
- `rules.py` with `MAX_ATTEMPTS`, `approval_limit`, `require_status` and the status after a decision or a failure.
- Tests change only in their imports.

**Success criteria**

- [x] `uv run pytest -q backend` passes, including a test that the live OpenAPI document equals `backend/tests/openapi.json`, which was saved before the first move.
- [x] A new `backend/tests/test_layout.py` fails if `SELECT`, `INSERT`, `UPDATE`, `DELETE` or `.execute(` appears in any backend source file other than `store.py`, `db.py` and `seed.py`, and passes.
- [x] `Grep "str\(run_id\)|parse_float" backend` shows `str(run_id)` nowhere and `parse_float` once, in `data.py`.
- [x] The not-in-progress conflict is written once. `Grep "not in_progress\|is \{row\['status'\]\}" backend` shows it in `rules.py` only.
- [x] `docs/STATUS.md` names the new modules. `npm run check:python` passes.

### Phase 2: the backend's routes by resource, and a thin entry point

**What it builds.** `routes/claims.py`, `records.py`, `documents.py`, `runs.py` and `dependencies.py`; `main.py` shrinks to the app, the lifespan, the routers and health.

**Success criteria**

- [x] `backend/main.py` is under 50 lines, and no file in `backend/` (tests aside) is over 300 lines. A test checks the second.
- [x] `test_layout.py` also fails if a backend source file other than a test imports `backend.main`, or if `store`, `rules` or `data` imports anything from `routes`.
- [x] The OpenAPI test passes (same routes, same `operation_id`s, same bodies).
- [x] `uv run pytest -q backend` passes with only imports and set-up changed in the existing tests.
- [x] `npm run dev:backend` starts and `Invoke-RestMethod http://127.0.0.1:8000/api/claims` returns the 25 claims.
- [x] `npm run check:python` and `npm run e2e` pass. `docs/STATUS.md` is updated.

### Phase 3: the harness

**What it builds.** `agent/harness/` with `model.py`, `agents.py`, `steps.py`, `todos.py` and `limits.py`, built from the code now in `agent/main.py` and `queue_run.py`. The old modules call it, so the product works as before.

- `steps.run_agent(agent, prompt, thread_id, on_step=None) -> str` streams the agent, passes each step to `on_step` and returns the last reply. It replaces the loop in `run()` and the one in `run_queue()`.
- `todos.todo_tool(save)` returns the `write_todos` tool. `limits.Run` has `admit(item_id)`, `unfinished(waiting_ids)`, the lock and the summary.
- `load_dotenv` leaves the import and goes to `__main__` (N4).
- New `agent/tests/test_harness.py` tests each piece with stub models and no word about claims.

**Success criteria**

- [x] `uv run pytest -q agent` passes. The new tests cover: an agent built by `build_agent` that retries a model that fails once, with the delay set to zero; the call limit raising; `steps_of` for a tool call, a tool result (cut at 400 characters), a reply and anything else; `run_agent` reporting steps in order and returning the last reply; `todo_tool` saving what it is given; and `Run.admit` refusing past the cap, `unfinished` naming retries and in-cap claims only.
- [x] `Grep -i "claim|policy|payout|decision|backend|/api/" agent/harness` finds nothing except the `left_for_handler` state in `todos.py` (assumption 2).
- [x] `uv run -m agent --help` still works.
- [x] `npm run check:python` passes. `docs/STATUS.md` is updated.

### Phase 4: one way to call the backend

*Built together with Phase 5, in the final layout, to avoid writing every test twice. The tests were green at the end of both.*

**What it builds.** `agent/undercover/backend.py`: a `Backend` class that owns the client, every path and the handling of a refusal, with typed answers; the tools, the runner and the queue agent switch to it.

- Methods in the product's terms: `claim`, `waiting_claims`, `start_claim`, `fail_claim`, `record_decision`, `pay`, `add_step`, `policy_text`, `customer_text`, `contents`, `read_section`, `claim_instructions`, `queue_instructions`, `start_run`, `set_todos`, `finish_run`. `Backend.connect()` reads `BACKEND_URL`.
- A refusal (any 4xx) raises `Refused`, a `ToolException` whose text is `Refused (404): <body>`; a 5xx raises as now.
- The tools become `claim_tools(backend)` with `handle_tool_error=True`. `work_claim` and the queue agent take a `Backend`. `conftest.py` builds one over `TestClient(app)` and no longer patches module attributes.
- The tests that read the backend's state do it through the same `Backend`, so no `/api/` string remains in `agent/`, tests included.
- New `agent/tests/test_backend_client.py`: each method returns what it should, a 404 and a 409 raise `Refused` with the same text as before, a 500 raises.

**Success criteria**

- [x] `uv run pytest -q agent` passes, with the existing tests keeping their assertions and the refusal texts unchanged (`Refused (404)` still starts the text a tool returns).
- [x] `Grep "/api/|https?://|localhost|httpx" agent` shows hits only in `agent/undercover/backend.py` and the OpenRouter address in `agent/harness/model.py`.
- [x] `Grep "client\.(get|post|put)|\.json\(\)|is_error|is_success|status_code" agent` shows hits only in `agent/undercover/backend.py`.
- [x] `Grep -c "httpx.Client" agent` gives one.
- [x] `npm run check:python` passes. `docs/STATUS.md` is updated.

### Phase 5: the agent's layout, with the checks that keep it

**What it builds.** Move the rest into `agent/undercover/`: `tools.py`, `claim_agent.py` (from `runner.py` and `main.run`) and `queue_agent.py` (from `queue_run.py`). Delete `agent/main.py`, `runner.py`, `queue_run.py` and the old `tools.py`. `__main__.py` creates the `Backend` and calls them. Finishing a run is one function (N2). `describe` and the queue's line formatting use the typed models (N1). Split the tests to match: `test_claim_agent.py`, `test_queue_agent.py`, `test_harness.py`, `test_backend_client.py`.

**Success criteria**

- [x] `uv run pytest -q agent` passes with every existing test still there under its new file.
- [x] `agent/tests/test_layout.py` passes, and fails when it should. It checks, by reading each file's imports: `agent/harness` imports nothing from `agent.undercover`, `agent.__main__` or `backend`; nothing in `agent/undercover` imports `agent.__main__` or `backend`; nothing imports `agent.__main__` except tests. It also checks that no `agent/` file other than tests is named `main`, `utils`, `helpers` or `runner`, that no source file is over 300 lines, and that `/api/` appears only in `undercover/backend.py`.
- [x] I prove the test works: add `from agent.undercover import backend` to a harness file, see the test fail, remove it.
- [x] The search for the review's count: `Grep "/api/|localhost|https?://" agent --glob "!tests/**"` shows the paths only in `undercover/backend.py`, with each path once, and the OpenRouter address once in `harness/model.py`.
- [x] `Glob agent/**/*.py` shows no `main.py`, `runner.py` or `queue_run.py`.
- [x] `uv run -m agent --help` works. `npm run check:python` passes.
- [x] `docs/TECH_STACK.md` and `docs/STATUS.md` describe the layout and name the harness and the UnderCover side.

### Phase 6: the instructions as goals

**What it builds.** New `backend/instructions/claim.md` and `queue.md`, written from `data/policy_wording.md`, `data/claims_manual.md` and `data/company.json`, with `data/evals/` and `data/security/` closed.

- Each says who the agent is, what it is trying to achieve, the rules it must not break, how to tell it is done, and what the summary or the explanation contains.
- The claim instructions: the wording first and the manual where it is silent, and the agent finds what it needs in them, not in the instructions; the explanation is two or three sentences naming a section; sign-off over $1,000 is expected, so the agent does not retry a blocked payment; decide and pay once.
- The queue instructions: work the waiting claims up to the cap, in the order it judges best, keep a to-do list the handlers can watch, never start a claim that is not waiting, retry a failed claim once more and leave a second failure for a handler, check that no waiting claim within the cap is missed, and finish with a summary of counts, what waits for sign-off and what was left, and why.
- No numbered list, no tool names in an order, no copied deductible, payout steps, filing window or repeat-claim rule.
- New `backend/tests/test_instructions.py`: no line starts with a number and a full stop, no file is over 400 words for the claim and 250 for the queue, and the words "get_claim", "record_decision" and "pay_claim" do not appear in a numbered context.

**Success criteria**

- [x] The test passes. Before and after word counts, from `wc -w`: claim 908 to under 400 (target about 300), queue 466 to under 250 (target about 180). I report both.
- [x] I read both files against the rules in this plan and list any rule that is in the instructions and also in the wording or the manual.
- [x] `uv run pytest -q` passes, including the agent tests that check a system prompt equals the instructions.
- [x] The instructions page in the browser shows both texts (checked in Phase 8).
- [x] `npm run check:python` passes.

### Phase 7: the dashboard

**What it builds.** The two small fixes from N10, nothing else.

- `STATUSES` becomes a `const` array and `Status` is its element type, so the set is written once.
- `RunPanel` keys by position.
- Tests: a run with two items of the same text renders both.

**Success criteria**

- [x] `npm run check:ts` passes with the vitest coverage threshold unchanged (80%), including a test for the repeated item text.
- [x] `Grep "waiting.*in_progress.*awaiting_sign_off" dashboard/src` shows the list once, outside the tests.
- [x] `npm run e2e` passes.

### Phase 8: restart from a clean state and run five claims

**What it does.** No code.

- Stop everything: the dev servers, the Playwright servers, any process on 8000, 5173, 8001, 5174. Ask before ending any process I did not start, as before.
- `uv run -m backend.seed`, `npm run dev`, then `uv run -m agent --limit 5` on the default model, with the Playwright MCP server watching `http://localhost:5173`.

**Success criteria**

- [x] The queue page shows the to-do list filling in and being ticked off, then the summary; light and dark mode are checked; a claim page shows its steps and the sections it read; the instructions page shows both new texts.
- [x] `GET /api/claims` shows exactly five claims decided, awaiting sign-off or left for a handler, 20 waiting, none in progress.
- [x] I report what each of the five decided, next to the last hand check in `docs/STATUS.md` (CLM-1001 approved for $420.00 and paid, CLM-1008 and CLM-1011 approved and waiting for sign-off, CLM-1018 referred, CLM-1010 declined). If one differs I say which and why I think so, without opening `data/evals/`. These are not an answer key.
- [x] I reseed afterwards.

### Phase 9: the documents, and the report

**What it builds.** `docs/PROCESS.md` and `docs/CODE_STANDARDS.md` as in section 4, `docs/TECH_STACK.md` and `docs/STATUS.md` as the product now is, and the plan ticked off. The final report answers step 5 gap by gap.

**Success criteria**

- [x] `PROCESS.md` and `CODE_STANDARDS.md` have the changes in section 4, each document stays short, and the voice matches.
- [x] Every rule the standards mark as checked has a test that exists and passes: `Grep "def test_" agent/tests/test_layout.py backend/tests/test_layout.py backend/tests/test_instructions.py` lists them.
- [x] `docs/TECH_STACK.md` and `docs/STATUS.md` show the agent's layout (the harness and the UnderCover side), the backend's, and the new checks. `docs/SPEC.md` needs no change; I confirm that.
- [x] No threshold lowered, no rule turned off and no file excluded: `git diff 779273d -- pyproject.toml eslint.config.js lefthook.yml package.json playwright.config.ts` shows no loosened setting.
- [x] `npm run check` passes: ruff, pyright, pytest at least 80% coverage, ESLint, Prettier, tsc, vitest at least 80%, and every Playwright test.
- [x] The final report lists, for each gap in section 1, the change and the file, and shows the three searches (the paths, the SQL, the imports) and the word counts.
