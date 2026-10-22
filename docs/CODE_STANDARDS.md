# Code standards

1. Keep it simple, do not overcomplicate.
2. Comments only when necessary.
3. Be concise: no emojis. The product has no README of its own: `docs/STATUS.md` says what's built and how to run it. Never edit the root `README.md`, which belongs to the course.
4. IMPORTANT: avoid overly defensive code. Handle exceptions only when necessary.
5. Use uv: ALWAYS `uv run`, NEVER `python3`.
6. TypeScript: strict mode, never `any`.
7. Money: never use floats for amounts. Use `Decimal` in Python and whole cents in TypeScript, and round to the cent only when a payout is worked out.