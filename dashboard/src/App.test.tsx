import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "./App";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows the header and the queue", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(Response.json([]))),
  );
  render(<App />);
  expect(screen.getByRole("link", { name: "UnderCover" })).toBeDefined();
  expect(await screen.findByText("Claims queue")).toBeDefined();
});
