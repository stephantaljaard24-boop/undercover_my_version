import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { QueuePage } from "./QueuePage";

const claim = {
  claim_id: "CLM-1001",
  customer_name: "Maya Patel",
  claim_type: "trip_delay",
  summary: "Flight home canceled",
  submitted_on: "2026-06-24",
  amount_claimed: "420.00",
  status: "waiting",
  decision: null,
  payout: null,
};

const claims = [
  claim,
  { ...claim, claim_id: "CLM-1002", status: "in_progress" },
  {
    ...claim,
    claim_id: "CLM-1003",
    status: "awaiting_sign_off",
    decision: "approve",
    payout: "1500.00",
    amount_claimed: "1550.50",
  },
  {
    ...claim,
    claim_id: "CLM-1004",
    status: "decided",
    decision: "decline",
    payout: "0.00",
  },
  {
    ...claim,
    claim_id: "CLM-1005",
    status: "decided",
    decision: "approve",
    payout: "420.00",
  },
];

const run = {
  run_id: 1,
  claim_limit: 5,
  todos: [
    { text: "CLM-1001", status: "done" },
    { text: "CLM-1002", status: "in_progress" },
    { text: "CLM-1003", status: "todo" },
    { text: "CLM-1004", status: "left_for_handler" },
  ],
  summary: null,
  finished: false,
};

function backend(list: object[] = claims, current: object | null = null) {
  return vi.fn((url: string) =>
    Promise.resolve(
      Response.json(url === "/api/runs/current" ? current : list),
    ),
  );
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

async function show(fetchMock: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("fetch", fetchMock);
  render(<QueuePage />);
  await act(() => vi.advanceTimersByTimeAsync(0));
}

it("shows the counts and a row for every claim", async () => {
  await show(backend());

  const counts = within(
    screen.getByRole("region", { name: "Claims by status" }),
  );
  expect(counts.getByText("Waiting").parentElement?.textContent).toBe(
    "1Waiting",
  );
  expect(counts.getByText("Decided").parentElement?.textContent).toBe(
    "2Decided",
  );
  expect(counts.getByText("In progress").parentElement?.textContent).toBe(
    "1In progress",
  );

  expect(screen.getAllByRole("row")).toHaveLength(6);
  const sign = screen.getByRole("row", { name: /CLM-1003/ });
  expect(within(sign).getByText("Waiting for sign-off")).toBeDefined();
  expect(within(sign).getByText("$1,550.50")).toBeDefined();
  expect(within(sign).getByText("Approved")).toBeDefined();
  expect(within(sign).getByText("$1,500.00")).toBeDefined();
  expect(
    within(screen.getByRole("row", { name: /CLM-1004/ })).getByText("Declined"),
  ).toBeDefined();
  expect(screen.getAllByText("Jun 24, 2026").length).toBeGreaterThan(0);
  expect(
    screen.getByRole("link", { name: "CLM-1001" }).getAttribute("href"),
  ).toBe("#/claims/CLM-1001");
});

it("asks for the queue again every 3 seconds", async () => {
  const fetchMock = backend();
  await show(fetchMock);
  expect(fetchMock).toHaveBeenCalledTimes(2);
  await act(() => vi.advanceTimersByTimeAsync(3000));
  expect(fetchMock).toHaveBeenCalledTimes(4);
});

it("says so when the queue cannot be loaded, and tries again", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValueOnce(new Response("", { status: 500 }))
    .mockImplementation((url: string) => backend()(url));
  await show(fetchMock);
  expect(screen.getByText("The queue could not be loaded.")).toBeDefined();
  await act(() => vi.advanceTimersByTimeAsync(3000));
  expect(screen.getByText("Claims queue")).toBeDefined();
});

it("counts claims left for a handler and shows their badge", async () => {
  await show(
    backend([{ ...claim, claim_id: "CLM-1006", status: "needs_handler" }]),
  );
  const counts = within(
    screen.getByRole("region", { name: "Claims by status" }),
  );
  expect(
    counts.getByText("Left for a handler").parentElement?.textContent,
  ).toBe("1Left for a handler");
  expect(
    within(screen.getByRole("row", { name: /CLM-1006/ })).getByText(
      "Left for a handler",
    ),
  ).toBeDefined();
});

it("shows the current run with its to-do list", async () => {
  await show(backend(claims, run));
  const panel = within(screen.getByRole("region", { name: "Current run" }));
  expect(panel.getByText("Up to 5 claims. Running.")).toBeDefined();
  expect(panel.getByText("Done").nextSibling?.textContent).toBe("CLM-1001");
  expect(panel.getByText("In progress")).toBeDefined();
  expect(panel.getByText("To do")).toBeDefined();
  expect(panel.getByText("Left for a handler")).toBeDefined();
  expect(panel.queryByText("Summary")).toBeNull();
});

it("shows the summary when the run has finished", async () => {
  await show(
    backend(claims, {
      ...run,
      claim_limit: 1,
      todos: [],
      summary: "One claim approved.",
      finished: true,
    }),
  );
  const panel = within(screen.getByRole("region", { name: "Current run" }));
  expect(panel.getByText("Up to 1 claim. Finished.")).toBeDefined();
  expect(panel.getByText("No to-do list yet.")).toBeDefined();
  expect(panel.getByText("One claim approved.")).toBeDefined();
});

it("shows no run panel when there has been no run", async () => {
  await show(backend());
  expect(screen.queryByRole("region", { name: "Current run" })).toBeNull();
});
