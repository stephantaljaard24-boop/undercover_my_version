# Code standards

1. Keep it simple, do not overcomplicate.
2. Comments only when necessary.
3. Be concise: no emojis. The product has no README of its own: `docs/STATUS.md` says what's built and how to run it. Never edit the root `README.md`, which belongs to the course.
4. IMPORTANT: avoid overly defensive code. Handle exceptions only when necessary.
5. Use uv: ALWAYS `uv run`, NEVER `python3`.
6. TypeScript: strict mode, never `any`.
7. Money: never use floats for amounts. Use `Decimal` in Python and whole cents in TypeScript, and round to the cent only when a payout is worked out.
8. One job per module, named for it. No `main`, `utils`, `helpers` or `runner`, except an entry point, which only wires things up and which nothing imports. A Python source file stays under 300 lines. (`test_layout.py`)
9. Say each thing once. A URL path, host name, SQL statement, status rule or constant is written in one place and used from there. The agent reaches the backend only through `agent/undercover/backend.py`, and the backend's SQL lives only in `backend/store.py`. (`test_layout.py`)
10. Layers point one way: entry point, then the product, then the harness; routes, then rules and store, then the database. The harness (`agent/harness/`) knows nothing about claims, and nothing in `agent/` imports `backend`. (`test_layout.py`)
11. Callers get typed answers. Code outside a client never sees a URL, a response object or a status code, and answers are models, not dicts.
12. Instructions to an agent are goals and limits: who it is, what it is to achieve, the rules it must not break, how to tell it is done, what to report. No numbered steps, no tool names and no tool order, and no rule copied from the wording or the manual. Each file stays under 400 words. (`test_instructions.py`)
