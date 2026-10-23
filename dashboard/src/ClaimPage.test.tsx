import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ClaimPage } from "./ClaimPage";

const claim = {
  claim_id: "CLM-1001",
  policy_id: "POL-2001",
  customer_id: "CUS-3001",
  claim_type: "trip_delay",
  submitted_on: "2026-06-24",
  incident_date: "2026-06-18",
  incident_location: "Rome, Italy",
  summary: "Flight home canceled by the airline",
  story: "My flight home from Rome was canceled.",
  items: [
    {
      description: "Airport hotel",
      category: "accommodation",
      amount: "245.00",
    },
    { description: "Dinner", category: "meals", amount: "95.50" },
  ],
  amount_claimed: "340.50",
  documents: [
    { name: "Hotel receipt", type: "receipt", content: "One night, $245.00." },
  ],
  status: "waiting",
  decision: null,
  payment: null,
};

const policy = {
  policy_id: "POL-2001",
  plan: "premium",
  add_ons: ["electronics_plus"],
  purchased_on: "2026-04-22",
  trip: {
    destination: "Rome, Italy",
    departs_on: "2026-06-10",
    returns_on: "2026-06-18",
    trip_cost: "3100.00",
  },
  travelers: ["Maya Patel"],
};

const customer = {
  customer_id: "CUS-3001",
  name: "Maya Patel",
  customer_since: "2023-04-11",
  previous_claims: [
    {
      claim_id: "CLM-0412",
      filed_on: "2024-08-19",
      claim_type: "baggage_delay",
      summary: "Checked bag arrived late",
      outcome: "approved",
      amount_paid: "140.00",
    },
  ],
};

const decision = {
  decision: "approve",
  payout: "340.50",
  explanation: "The delay was long enough.",
  policy_section: "3. Trip Delay",
};

function backend(overrides: object, steps: object[] = [], earlier = true) {
  return vi.fn((url: string) => {
    let body: unknown = { ...claim, ...overrides };
    if (url.endsWith("/steps")) body = steps;
    else if (url.startsWith("/api/policies/")) body = policy;
    else if (url.startsWith("/api/customers/"))
      body = earlier ? customer : { ...customer, previous_claims: [] };
    return Promise.resolve(Response.json(body));
  });
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
  render(<ClaimPage claimId="CLM-1001" />);
  await act(() => vi.advanceTimersByTimeAsync(0));
}

it("shows a waiting claim in full", async () => {
  await show(backend({}));
  expect(screen.getByText("CLM-1001")).toBeDefined();
  expect(screen.getByText("Waiting")).toBeDefined();
  expect(
    screen.getByText("My flight home from Rome was canceled."),
  ).toBeDefined();
  expect(screen.getByText("Airport hotel")).toBeDefined();
  expect(screen.getByText("$95.50")).toBeDefined();
  expect(screen.getByText("Total claimed")).toBeDefined();
  expect(screen.getByText("$340.50")).toBeDefined();
  expect(screen.getByText("Hotel receipt")).toBeDefined();
  expect(screen.getByText("One night, $245.00.")).toBeDefined();
  expect(screen.getByText("Electronics plus")).toBeDefined();
  expect(screen.getByText("$3,100.00")).toBeDefined();
  expect(
    screen.getByText(/Checked bag arrived late, approved, paid \$140.00/),
  ).toBeDefined();
  expect(screen.getByText("No decision yet.")).toBeDefined();
  expect(screen.getByText("Nothing yet.")).toBeDefined();
});

it("shows the steps of a claim in progress and keeps watching it", async () => {
  const fetchMock = backend({ status: "in_progress" }, [
    { kind: "tool_call", text: 'get_claim {"claim_id": "CLM-1001"}' },
    { kind: "tool_result", text: "A trip delay claim" },
  ]);
  await show(fetchMock);
  expect(screen.getByText("In progress")).toBeDefined();
  expect(screen.getByText("The agent is working on this claim.")).toBeDefined();
  expect(screen.getByText('get_claim {"claim_id": "CLM-1001"}')).toBeDefined();
  expect(screen.getByText("Tool call")).toBeDefined();
  expect(screen.getByText("Tool result")).toBeDefined();
  const calls = fetchMock.mock.calls.length;
  await act(() => vi.advanceTimersByTimeAsync(1999));
  expect(fetchMock.mock.calls).toHaveLength(calls);
  await act(() => vi.advanceTimersByTimeAsync(1));
  expect(fetchMock.mock.calls.length).toBeGreaterThan(calls);
});

it("shows a decided and paid claim, and stops watching it", async () => {
  const fetchMock = backend(
    { status: "decided", decision, payment: { amount: "340.50" } },
    [{ kind: "reply", text: "Approved." }],
    false,
  );
  await show(fetchMock);
  expect(screen.getByText("Approved")).toBeDefined();
  expect(screen.getByText("The delay was long enough.")).toBeDefined();
  expect(screen.getByText("Policy section: 3. Trip Delay")).toBeDefined();
  expect(screen.getByText("Paid $340.50.")).toBeDefined();
  expect(screen.getByText("Reply")).toBeDefined();
  expect(screen.getByText("None.")).toBeDefined();
  const calls = fetchMock.mock.calls.length;
  await act(() => vi.advanceTimersByTimeAsync(10000));
  expect(fetchMock.mock.calls).toHaveLength(calls);
});

it("shows a payment blocked until a handler signs off", async () => {
  await show(
    backend({
      status: "awaiting_sign_off",
      decision: { ...decision, payout: "1500.00" },
    }),
  );
  expect(screen.getByText("Waiting for sign-off")).toBeDefined();
  expect(screen.getByText("$1,500.00")).toBeDefined();
  expect(
    screen.getByText("Payment blocked: waiting for a handler's sign-off."),
  ).toBeDefined();
});

it("shows an approved claim that is not paid yet", async () => {
  await show(backend({ status: "decided", decision }));
  expect(screen.getByText("Not paid yet.")).toBeDefined();
});

it("shows a declined claim with no payment", async () => {
  await show(
    backend({
      status: "decided",
      decision: { ...decision, decision: "decline", payout: "0.00" },
    }),
  );
  expect(screen.getByText("Declined")).toBeDefined();
  expect(screen.queryByText(/Paid|Not paid|blocked/)).toBeNull();
});

it("says so when the claim cannot be loaded", async () => {
  await show(vi.fn(() => Promise.resolve(new Response("", { status: 404 }))));
  expect(screen.getByText("The claim could not be loaded.")).toBeDefined();
});
