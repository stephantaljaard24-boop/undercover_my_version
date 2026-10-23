import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { InstructionsPage } from "./InstructionsPage";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows the agent's instructions", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(new Response("You are the UnderCover Agent."))),
  );
  render(<InstructionsPage />);
  expect(
    await screen.findByText("You are the UnderCover Agent."),
  ).toBeDefined();
  expect(screen.getByText("Agent instructions")).toBeDefined();
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
