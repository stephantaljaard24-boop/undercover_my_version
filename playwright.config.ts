import { tmpdir } from "node:os";
import { join } from "node:path";
import { defineConfig } from "@playwright/test";

// The tests run their own backend and dashboard, on their own database and
// ports, so they never touch the data that `npm run dev` uses.
const database = join(tmpdir(), "undercover-e2e.db");

export default defineConfig({
  testDir: "e2e",
  outputDir: "e2e/test-results",
  reporter: "list",
  workers: 1,
  use: { baseURL: "http://localhost:5174" },
  webServer: [
    {
      command: "node e2e/stand-in-agent.ts",
      url: "http://127.0.0.1:8003",
      reuseExistingServer: false,
    },
    {
      command:
        "uv run -m backend.seed && uv run -m uvicorn backend.main:app --port 8001",
      url: "http://127.0.0.1:8001/api/health",
      env: {
        UNDERCOVER_DB: database,
        DATABASE_URL: "",
        UNDERCOVER_AGENT: "http://127.0.0.1:8003",
      },
      reuseExistingServer: false,
    },
    {
      command: "npx vite dashboard --port 5174 --strictPort",
      url: "http://localhost:5174",
      env: { BACKEND_URL: "http://127.0.0.1:8001" },
      reuseExistingServer: false,
    },
  ],
});
