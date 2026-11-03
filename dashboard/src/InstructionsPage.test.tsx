import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { InstructionsPage } from "./InstructionsPage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows the instructions for the queue and for a claim", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve(
        new Response(
          url.endsWith("/queue") ? "You run the queue." : "You work one claim.",
        ),
      ),
    ),
  );
  render(<InstructionsPage />);
  expect(await screen.findByText("You run the queue.")).toBeDefined();
  expect(screen.getByText("You work one claim.")).toBeDefined();
  expect(screen.getByText("Agent instructions")).toBeDefined();
  expect(screen.getByText("Running the queue")).toBeDefined();
  expect(screen.getByText("Working a claim")).toBeDefined();
});

it("says so when the instructions cannot be loaded", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(new Response("", { status: 500 }))),
  );
  render(<InstructionsPage />);
  expect(
    await screen.findByText("The instructions could not be loaded."),
  ).toBeDefined();
});
