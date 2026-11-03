# Tech stack

- `backend/`: FastAPI and SQLite. It also serves the wording and the manual by section, and keeps each run and its to-do list. Every API operation has an `operation_id`, a one-line docstring and no optional inputs. Paying a claim is a separate operation that takes the amount.
- `agent/`: LangChain's `create_agent` on OpenRouter, with no other agent framework. A queue agent runs the whole queue from a to-do list and hands each claim to a claim agent that works it from a clean start. Two entry points: a queue run, with an optional cap on claims, and a single claim, which takes a claim id. Both reach claims, the wording, the manual and their instructions only through the backend's API. Retries and call limits are LangChain middleware. It uses `deepseek/deepseek-v4.1-flash` with low reasoning effort by default, or the model in the environment variable `MODEL_NAME` if set, such as `openrouter/free`.
- `dashboard/`: React, Vite and TypeScript.
- `e2e/`: Playwright tests.
- `data/`: the business data the backend starts from. The agent never sees `data/evals/`, which holds the answer key.

Python 3.12 with uv, all in the root `pyproject.toml`. Node 26. The OpenRouter key is `OPENROUTER_API_KEY` in `.env`.
