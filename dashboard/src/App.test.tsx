import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "./App";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.location.hash = "";
});

function stubBackend() {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      Promise.resolve(
        url === "/api/instructions"
          ? new Response("Be careful.")
          : Response.json([]),
      ),
    ),
  );
}

it("shows the header and the queue", async () => {
  stubBackend();
  render(<App />);
  expect(screen.getByRole("link", { name: "UnderCover" })).toBeDefined();
  expect(screen.getByRole("link", { name: "Queue" })).toBeDefined();
  expect(await screen.findByText("Claims queue")).toBeDefined();
});

it("follows the hash to the instructions and a claim", async () => {
  stubBackend();
  render(<App />);
  act(() => {
    window.location.hash = "#/instructions";
  });
  expect(await screen.findByText("Be careful.")).toBeDefined();
  act(() => {
    window.location.hash = "#/claims/CLM-1001";
  });
  expect(
    await screen.findByText("The claim could not be loaded."),
  ).toBeDefined();
});
