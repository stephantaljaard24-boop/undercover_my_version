# Process

`uv sync` and `npm install` at the repo root install everything, including a git pre-commit hook. `npm run dev` starts the backend, the dashboard and the agent's service, with `.env` passed to the backend and the service. `npm run seed` resets the Supabase database to the starting queue, and `uv run -m backend.seed` resets the SQLite one.

`npm run check` runs every check:

- Python: ruff (lint and format), pyright, and pytest with 80% coverage
- TypeScript: ESLint, Prettier, tsc, and vitest with 80% coverage
- Playwright end-to-end tests

The checks need no `.env`: the Python tests run on SQLite and an in-memory saver, the end-to-end tests on their own backend, database and stand-in for the agent's service, and none reaches Supabase, Langfuse or OpenRouter.

The pre-commit hook runs the format, lint, type and unit test checks on every commit.

## Planning

When asked to plan, as in "Please plan the pilot", write the plan to `docs/PLAN.md` and write no code.

- Split the work into phases, usually 5 or 6, each building on the last.
- Start the plan with a short "Open questions and assumptions" section: anything the documents leave unclear, and what you assumed.
- Give each phase detailed success criteria that you can verify yourself: tests that pass, commands and their output, API calls and their responses, and pages you check in the browser with the Playwright MCP server. Write each one as a checkbox.
- Put a "Layout" section after the open questions: each module the work adds or changes, its one job, what imports what, and the reason for each cut. Name a module for its job, never for the feature that added it.
- If the work changes the API, list saving the new `backend/tests/openapi.json` as a step. The test's failure message gives the command. A restructure leaves the API alone, so that test must stay green without a new copy.
- End every plan with a review phase. Its criteria are the checks in `docs/CODE_STANDARDS.md`, each with the search or test that shows it.
- Then stop and wait until you are asked to implement the plan.

## Implementing

When asked to implement the plan, as in "Please implement the plan for the pilot", build every phase in order without stopping. For each phase:

1. Build it, with tests.
2. Check every success criterion and fix whatever fails.
3. Tick off its criteria in the plan's file, such as `docs/PLAN.md` or `docs/PLAN_HARNESS.md`, and update `docs/STATUS.md`.
4. Commit. The pre-commit hook runs the checks; if it fails, fix the problem and commit again.

When the last phase is done, read the whole diff as a reviewer would and fix what you would ask to change, then run `npm run check` and report the results.

## Rules

- Add tests with each change. Tests never call a model, the end-to-end tests included: use a stub model, or test the screens with data already in place.
- When a build changes the agent, run it on one claim with a real model before you hand the work over, with `MODEL_NAME=openrouter/free` unless asked otherwise, and report what it decided. This is a check by hand, not a test. For any live run with the real model, reseed first and cap the run at five claims.
- Outside a plan, commit each change once you have checked it.
- Before you add a call, query, path or constant, search for it. If it exists, use it. If it is written in a second place, move both to one.
- `npm run check` includes the layout tests, which fail on a backend path or SQL written in the wrong place, an import that points the wrong way, a vague file name and a Python source file over 300 lines.
- Run `npm run check` before you hand work over.
- Never use `git commit --no-verify`.
- Never lower a threshold, turn off a rule or exclude a file to get a green run. If a rule looks wrong, stop and ask.
- Keep `docs/STATUS.md` up to date.
- Never push.
- Don't open `data/evals/` unless you're asked to.
- Everything must work on Windows: write `package.json` scripts as `uv run` commands or `.mjs` files.
