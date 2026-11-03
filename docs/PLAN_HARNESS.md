# Plan: the agent's harness

The pilot's code organizes the agent's work: it feeds the agent one claim at a time, hands it the whole policy wording, and leaves a failed claim stuck. This build moves that organizing into the agent. One run of the UnderCover Agent works the queue from a to-do list it keeps, hands each claim to a fresh helper, looks up the sections of the wording and the claims manual it needs, and recovers from failures by itself. It works from `docs/HARNESS.md`, in six phases, each building on the last.

## Open questions and assumptions

1. **"Left for a handler" is a fifth status.** The queue gets `needs_handler`, shown as "Left for a handler" in Raspberry (the brand's fifth color). A claim fails when the helper raises an error, or ends without recording a decision. The first failure puts it back to `waiting`; the second puts it in `needs_handler`. The backend counts the attempts, so a re-run on a fresh process can't lose count. Reseeding resets them.
2. **The cap counts claims, not attempts.** `--limit 5` lets a run start at most five different claims. Retrying a claim that failed doesn't use up the cap. A run with no cap may start every claim that is waiting when it begins. The rest stay `waiting`.
3. **A named claim skips the queue agent.** `uv run -m agent CLM-1001` runs the claim helper directly, with the same recovery and no to-do list. It is the cheap way to try one claim, and a queue agent would add nothing.
4. **One claim at a time.** The queue agent may ask for several claims in one turn, so `work_claim` takes a lock and the helpers run one after another. The spec says one at a time, and it keeps the cap and the database simple.
5. **The to-do list is our own tool, not LangChain's `TodoListMiddleware`.** That middleware has three states and keeps the list inside the agent's private state. The brief needs four (to do, in progress, done, left for a handler) and a list the dashboard can read, so `write_todos` replaces the whole list and the backend stores it on the run. The dashboard shows the latest run.
6. **The helper is a fresh `create_agent` per claim.** It gets the claim instructions, a new thread id and the claim tools, and the queue agent sees it as one tool, `work_claim`, whose result is a single line. That is how the queue agent's context stays small however long the run is. This is LangChain's own `create_agent`, as the tech stack asks. `deepagents` is installed for the course but isn't used.
7. **Looking things up by section.** A section is a numbered `##` heading in `data/policy_wording.md` or `data/claims_manual.md`. Two operations serve them: a contents list for a document, and one section's text. Reading a section goes through `POST /api/claims/{claim_id}/reads` so the backend can record what the agent read for that claim; it is a POST only because it writes that record. The title and the manual's version line are not sections. The whole-document `get_policy_wording` operation is removed.
8. **Recovery has layers.** Transient errors (a timeout, a provider error, a failing tool) are retried by LangChain's `ModelRetryMiddleware` and `ToolRetryMiddleware`. A runaway loop is cut off by `ModelCallLimitMiddleware`. Anything that still gets through is caught in `work_claim`, which reports the failure, so one bad claim can't stop the run. The backend is the last guard: it refuses a second decision or a second payment, so retrying can't decide or pay twice.
9. **A failure after the approval.** If a helper fails after recording an approval and before paying, the claim is already decided, so it isn't put back in the queue. `work_claim` makes the one payment itself (the backend still refuses it if it is over $1,000 or already paid) and says so in its line.
10. **The check for missed claims is a refusal.** `finish_run` is how the queue agent ends the run. It refuses, naming the claims, if a waiting claim is still within the cap: a claim not yet started while the cap has room, or a failed claim waiting for its second try. The agent learns this the way it learns about a blocked payment. If the queue agent ends its turn without calling it, the runner records its last reply as the run's summary.
11. **Instructions come in two parts.** `backend/instructions/queue.md` runs the queue and `backend/instructions/claim.md` works a claim. Two operations serve them and the instructions page shows both. I write them from `data/policy_wording.md` and `data/claims_manual.md` and don't open `data/evals/`.
12. **The model.** The default becomes `deepseek/deepseek-v4.1-flash` with low reasoning effort. `MODEL_NAME` overrides it and, as now, then sends no reasoning setting.
13. **Tests.** Stub models only. Retry delays are a constant that tests set to zero. The live runs use the default model, as the brief asks, after a reseed and capped at five claims; they cost a few cents of OpenRouter credit.
14. **Old operations are removed when their last user does.** Phases 1 and 2 only add to the backend. `get_policy_wording` and `release_claim` go in Phase 3 with the agent that used them, and the single `/api/instructions` goes in Phase 5 with the dashboard page that used it.
15. **Unchanged.** Sign-off over $1,000, no real payments, no sign-in, and the agent never seeing `data/evals/` or `data/security/`.

## Phase 1: the wording and the manual, by section

**What it builds.** Backend operations to look a document up by section, and a record of what was read on each claim.

| Operation | Route | Returns |
|---|---|---|
| `get_contents` | `GET /api/documents/{document}/contents` | The numbers and titles of a document's sections, as text. `document` is `policy_wording` or `claims_manual` |
| `read_section` | `POST /api/claims/{claim_id}/reads` | Takes `document` and `section` (such as `"9"`). Records the read on the claim, once per section, and returns the section's text |
| `list_reads` | `GET /api/claims/{claim_id}/reads` | The sections read on a claim, in the order first read |

- `backend/documents.py`: splits a document on its `## N. Title` headings. A new `reads` table in `backend/db.py` (`claim_id`, `document`, `section`) and a `Read` model in `backend/models.py`. `backend/main.py` gets the three operations.
- The existing operations stay as they are for now.

**Why this way.** Cutting at the numbered headings gives the same sections a handler finds by number, such as "section 10 of the wording", and the contents list lets the agent choose what to read. Recording the read in the backend, as with decisions and payments, means the claim page can show it whatever the model does.

**Success criteria**

- [x] `uv run pytest -q backend` passes, with tests that:
  - [x] the wording's contents list 12 sections and the manual's list 14, with the titles as written;
  - [x] `read_section` returns the text of `claims_manual` section 9, starting with its heading and not running into section 10;
  - [x] reading the same section twice records one read, and `list_reads` returns the reads in order;
  - [x] an unknown document, section or claim gives 404, and the reset (`uv run -m backend.seed`) clears the reads;
  - [x] nothing from `data/evals/` or `data/security/` is read: the only sources are the two document files.
- [x] With `npm run dev:backend` running, `Invoke-RestMethod http://127.0.0.1:8000/api/documents/claims_manual/contents` lists 14 sections, and `Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/claims/CLM-1001/reads -ContentType application/json -Body '{"document":"claims_manual","section":"9"}'` returns the repeat-claims text. `GET /api/claims/CLM-1001/reads` then lists it. `uv run -m backend.seed` clears it.
- [x] `openapi.json` shows an `operationId` and a summary for each new operation and no optional inputs.
- [x] `docs/STATUS.md` describes the new operations. `npm run check:python` passes.

## Phase 2: failures, the run and its to-do list

**What it builds.** The backend's side of recovery and of the to-do list, and the two instruction operations.

- The fifth status `needs_handler`, and an `attempts` column on `claims`.
- `fail_claim` (`POST /api/claims/{claim_id}/fail`, taking `reason`): a claim in progress goes back to `waiting` with its attempts up by one, or to `needs_handler` when that makes two. It records the reason as a step of a new kind, `error`. Any other status gives 409, so a decided claim can never be put back and decided again.
- A `runs` table and four operations, with a `Run` model (id, the cap, the to-do list, the summary, and whether it is finished):

| Operation | Route | What it does |
|---|---|---|
| `start_run` | `POST /api/runs` | Takes `claim_limit`. Creates a run with an empty list and returns it |
| `set_todos` | `PUT /api/runs/{run_id}/todos` | Replaces the list. Each item has `text` and a `status` of `todo`, `in_progress`, `done` or `left_for_handler` |
| `finish_run` | `POST /api/runs/{run_id}/finish` | Takes `summary` and marks the run finished |
| `get_current_run` | `GET /api/runs/current` | The latest run, or null if there has been none |

- `backend/instructions/queue.md` and `backend/instructions/claim.md`, with `get_queue_instructions` (`GET /api/instructions/queue`) and `get_claim_instructions` (`GET /api/instructions/claim`). `backend/instructions.md` moves to `claim.md`, and `GET /api/instructions` keeps serving it until Phase 5. `queue.md` starts as a placeholder; Phase 4 writes it.

**Why this way.** Counting attempts in the backend makes "twice, then a handler" a rule of the system rather than something the agent has to remember. The to-do list is plain data on the run, so the agent writes it and the dashboard reads it with no new moving parts.

**Success criteria**

- [ ] `uv run pytest -q backend` passes, with tests that:
  - [ ] a first `fail_claim` puts the claim back to `waiting` and adds an `error` step with the reason;
  - [ ] a second puts it in `needs_handler`, and a third gives 409;
  - [ ] `fail_claim` on a waiting, decided or awaiting-sign-off claim gives 409;
  - [ ] a second `record_decision` on a decided claim gives 409 and leaves the first decision as it was; a second payment still gives 409;
  - [ ] the run operations: a new run is empty and unfinished, `set_todos` replaces the whole list, a status outside the four gives 422, `finish_run` stores the summary, `get_current_run` returns the latest run and null before any, and a reset clears runs and attempts;
  - [ ] the two instruction operations return the contents of their files.
- [ ] By hand against `npm run dev:backend`: starting CLM-1001 and failing it twice with `Invoke-RestMethod` ends in `needs_handler`, with two `error` steps. `uv run -m backend.seed` puts it back.
- [ ] `openapi.json` shows an `operationId` and a summary for each new operation and no optional inputs.
- [ ] `docs/STATUS.md` is updated. `npm run check:python` passes.

## Phase 3: the claim helper

**What it builds.** The agent that works one claim from a clean start, with the lookup tools, its own recovery and the new model.

- `agent/tools.py`: `get_contents(document)` and `read_section(claim_id, document, section)` replace `get_policy_wording`. The other tools stay.
- `agent/main.py`:
  - `DEFAULT_MODEL` becomes `deepseek/deepseek-v4.1-flash`.
  - A shared `build_agent` adds `ModelRetryMiddleware` and `ToolRetryMiddleware`, with the delay as a constant, and a `ModelCallLimitMiddleware`.
  - The claim helper fetches `/api/instructions/claim` and still records every step on the claim.
- `agent/runner.py`: `work_claim(claim_id, llm)` starts the claim and runs the helper. It then does one of three things:
  - if the helper raises an error, it calls `fail_claim` with the error;
  - if the claim is still in progress with no decision, it calls `fail_claim` with that reason;
  - if the helper failed after an approved decision with no payment, it makes the payment.
  
  It never raises. It returns one line, such as `CLM-1001: approve $420.00, paid`, `CLM-1002: failed (model is down), back in the queue` or `CLM-1002: failed again, left for a handler`.
- `backend/main.py`: remove `get_policy_wording` and `release_claim`, with their tests.
- `backend/instructions/claim.md`: rewritten from the wording and the manual. It tells the agent to:
  - read the claim, its policy and the customer's history;
  - read the contents of both documents, then only the sections the claim needs, as the manual's section 4 lists them: the benefit's section of the wording and section 9 of the wording, the manual's rules for the document list, the payout, repeat claims, meals and the interpretation notes that touch the claim;
  - decide by the wording first and the manual where the wording is silent;
  - record the decision, then pay;
  - never decide twice.

  It keeps the payout and explanation guidance from the pilot.
- `agent/__main__.py`: `uv run -m agent CLM-1001` calls `work_claim` and prints its line. The whole-queue path comes in Phase 4.

**Why this way.** Everything that can go wrong with one claim is handled where that claim is worked, and `work_claim` always leaves the claim in a sensible state. The next phase can then hand claims to it without worrying about what it does.

**Success criteria**

- [ ] `uv run pytest -q agent` passes. Tests use stub models and the backend's test client, and never call a model. They cover:
  - [ ] the tools: `get_contents` and `read_section` return the text and record the read, and a refusal comes back as text;
  - [ ] the pilot's behaviors still hold: approve and pay, an approval over the limit with the payment blocked, decline, refer, and steps recorded in order;
  - [ ] a helper that reads two sections, so `GET /api/claims/CLM-1001/reads` lists them;
  - [ ] a broken model: `work_claim` returns a failure line, the claim is `waiting`, and a second failure leaves it `needs_handler`;
  - [ ] a model that fails once and then works is retried by the middleware, with the retry delay set to zero, and the claim is decided;
  - [ ] a helper that ends without a decision: the claim goes back to `waiting` with an `error` step;
  - [ ] a helper that fails after an approval: the claim is paid once, and a payment the backend refuses leaves it `awaiting_sign_off`;
  - [ ] the helper's system prompt is the claim instructions;
  - [ ] the default model is `deepseek/deepseek-v4.1-flash`, and `MODEL_NAME` overrides it.
- [ ] By hand with the default model, after `uv run -m backend.seed` and with `npm run dev:backend` running, `uv run -m agent CLM-1001` records a decision with an explanation and a section. `GET /api/claims/CLM-1001/reads` lists the sections it read, and `GET /api/claims/CLM-1001/steps` its steps. I report what it decided and what it read. Then `uv run -m backend.seed`.
- [ ] `GET /api/policy-wording` and `POST /api/claims/{claim_id}/release` are gone from `openapi.json`.
- [ ] `docs/STATUS.md` is updated. `npm run check:python` passes.

## Phase 4: the queue agent

**What it builds.** The agent that runs the whole queue.

- `agent/queue_run.py`: `run_queue(limit, llm)` creates a run with `start_run` (the cap, or the number of waiting claims if none) and builds the queue agent on the queue instructions. Its four tools share the run's state (its id, the cap, the claims started so far and the lock):
  - `list_waiting_claims`: the waiting claims, one line each (id, type, submitted date, amount claimed and summary), so the agent can choose the order;
  - `write_todos(todos)`: calls `set_todos`;
  - `work_claim(claim_id)`: refuses with the reason if the claim isn't waiting or the cap is used up on other claims; otherwise takes the lock, calls the runner's `work_claim` and returns its one line, which is also printed;
  - `finish_run(summary)`: refuses, naming the claims, if a waiting claim is still within the cap (assumption 10); otherwise calls `finish_run` and returns.
- If the queue agent stops without finishing, its last reply becomes the summary. The summary is printed at the end.
- `agent/__main__.py`: `uv run -m agent` runs the queue, `uv run -m agent --limit 5` caps it, and `uv run -m agent CLM-1001` runs one claim (assumption 3).
- `backend/instructions/queue.md`: written from the wording and the manual. It says:
  - what the job is;
  - to read the waiting claims and write a to-do list first, then keep it up to date after each claim;
  - to choose the order, oldest first unless there is a reason;
  - to work one claim at a time with `work_claim` and trust its line;
  - that a claim that comes back failed goes in the list as a retry, and a claim left for a handler is marked `left_for_handler`;
  - to check the list against `list_waiting_claims` before `finish_run`;
  - to end with a short summary for the handlers: how many decided, approved, declined and referred, what waits for sign-off, and what was left for a handler and why.

**Why this way.** The queue agent decides the order and the plan, and everything it must not get wrong (the cap, the lock, the missed claims) is enforced in the tools, so a weak plan from the model can't break the run. Because it sees only one line per claim, its context grows by a few lines per claim and not by a whole claim's work.

**Success criteria**

- [ ] `uv run pytest -q agent` passes, with stub models that script both the queue agent and the helpers (the tests choose which one each model call belongs to by building them separately). New tests cover:
  - [ ] a full run: the to-do list is stored with `write_todos` and updated, `get_current_run` shows the final list and the summary, and the run is finished;
  - [ ] the cap: with a limit of 2, the third `work_claim` is refused and that claim stays `waiting`;
  - [ ] one bad claim doesn't stop the run: a helper that fails on CLM-1001 is followed by a decided CLM-1002;
  - [ ] a failed claim is tried again: the queue agent works CLM-1001 again and it is decided; if it fails twice it ends `needs_handler` and the run carries on;
  - [ ] the missed-claims check: `finish_run` with a claim still waiting inside the cap is refused and names it; after the claim is worked, `finish_run` succeeds; with the cap used up, claims outside it do not block the finish;
  - [ ] no claim is decided or paid twice: a second `work_claim` on a decided claim is refused, and a helper that records a second decision gets the backend's 409;
  - [ ] claims are worked one at a time even when the model asks for two in one turn;
  - [ ] the queue agent's context holds only the one-line report for each claim: none of a helper's tool calls or tool results appear in what the queue model sees;
  - [ ] a queue agent that stops without `finish_run` still leaves a run with its last reply as the summary;
  - [ ] the queue agent's system prompt is the queue instructions;
  - [ ] `agent.__main__` parses no arguments, `--limit 3` and a claim id as above.
- [ ] By hand with the default model: `uv run -m backend.seed`, `npm run dev:backend`, then `uv run -m agent --limit 2`. It prints a line for each of two claims and a summary. `GET /api/runs/current` shows the to-do list and the summary, and `GET /api/claims` shows the other 23 still `waiting`. I report what it did. Then `uv run -m backend.seed`.
- [ ] `docs/STATUS.md` is updated. `npm run check:python` passes.

## Phase 5: the dashboard

**What it builds.** What the team sees: the run's to-do list, the sections read, and the new status and step.

- `dashboard/src/api.ts`: the `needs_handler` status, the `error` step kind, a `Run` type with `fetchCurrentRun`, the reads in `fetchClaimView`, and the two instruction texts. `dashboard/src/labels.ts` and `styles.css`: "Left for a handler" in Raspberry, five counts, a to-do status pill for each of the four states, and the `error` step.
- `dashboard/src/QueuePage.tsx`: above the table, a "Current run" panel with the cap, the to-do list with a status on each item, and the summary once the run has finished. Nothing shows if there has been no run. It polls with the queue.
- `dashboard/src/ClaimPage.tsx`: a "What the agent read" panel listing each document and section, and `error` steps in the step list.
- `dashboard/src/InstructionsPage.tsx`: the queue instructions and the claim instructions, read only, each under its own heading.
- `backend/main.py`: remove the single `GET /api/instructions` and its tests.
- `e2e/support.ts`, `e2e/queue.spec.ts`, `e2e/claim.spec.ts` and `e2e/instructions.spec.ts`: updated, with the run, the reads, the new status and the two instructions put in place through the API.

**Why this way.** The run panel goes on the queue page, as the brief asks, so the team sees the plan and the progress in one place. The status and the step use the brand's colors, as the brand says, with Raspberry as the fifth.

**Success criteria**

- [ ] `vitest` passes with statement coverage of at least 80%, with tests for: the run panel with a mixed list, with a summary and with no run; the five counts; the "Left for a handler" badge; a claim page with reads and with an `error` step; and the instructions page with both texts.
- [ ] `e2e/queue.spec.ts` passes: through the API it starts a run, sets a list with all four item statuses, puts a claim in each of the five statuses, and the page shows the list, the five counts and the right badge on each claim.
- [ ] `e2e/claim.spec.ts` passes: through the API it records reads and a failure, and the claim page shows the sections read and the error. `e2e/instructions.spec.ts` shows both instructions.
- [ ] With `npm run dev` running and a run put in place through the API, the Playwright MCP server shows the queue page's run panel and the left-for-a-handler status in light and dark mode, in the brand's fonts and colors, and a claim page with its sections read.
- [ ] `GET /api/instructions` is gone from `openapi.json`.
- [ ] `docs/STATUS.md` is updated. `npm run check:ts` and `npm run e2e` pass.

## Phase 6: the whole harness, by hand, and the hand-over

**What it builds.** No new features: a live run, and the documents brought up to date.

- `docs/SPEC.md`: the claims manual moves out of "Not for now" and into the rules; a decision follows the wording and the manual, with the wording first; the queue gains the "left for a handler" status; the team also sees the to-do list for the current run and the sections the agent read; the agent works the whole queue in one run, can be capped, and recovers from failures by itself.
- `docs/TECH_STACK.md`: the agent's entry points (a queue run, and a single claim), its default model and the middleware it uses.
- `docs/STATUS.md`: what is built, how to run a capped run, one claim and the whole queue, how to reset, and what is left for later.

**Success criteria**

- [ ] After `uv run -m backend.seed`, with `npm run dev` running and the Playwright MCP server watching `http://localhost:5173`, `uv run -m agent --limit 5` on the default model works five claims on its own. The queue page shows the to-do list filling in and being ticked off, each claim's page shows its steps and the sections it read, and the summary appears at the end. I report what it did, including any claim that failed and was retried.
- [ ] After that run `GET /api/claims` shows exactly five claims decided, awaiting sign-off or left for a handler, and the other 20 still `waiting`. No claim is `in_progress`.
- [ ] `docs/SPEC.md`, `docs/TECH_STACK.md` and `docs/STATUS.md` describe the product as it now is, and every criterion in this plan is ticked.
- [ ] `npm run check` passes: ruff, pyright and pytest with at least 80% coverage, ESLint, Prettier, tsc and vitest with at least 80% coverage, and every Playwright test.
