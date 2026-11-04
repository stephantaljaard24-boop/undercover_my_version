import { toCents } from "./money";

/** Every status a claim can have, in the order the queue shows them. */
export const STATUSES = [
  "waiting",
  "in_progress",
  "awaiting_sign_off",
  "decided",
  "needs_handler",
] as const;
export type Status = (typeof STATUSES)[number];
export type Verdict = "approve" | "decline" | "refer";
export type StepKind = "tool_call" | "tool_result" | "reply" | "error";
export type TodoStatus = "todo" | "in_progress" | "done" | "left_for_handler";

/** Everything here shows amounts as whole cents. */
export interface ClaimSummary {
  claim_id: string;
  customer_name: string;
  claim_type: string;
  summary: string;
  submitted_on: string;
  amount_claimed: number;
  status: Status;
  decision: Verdict | null;
  payout: number | null;
}

export interface Item {
  description: string;
  category: string;
  amount: number;
}

export interface Document {
  name: string;
  type: string;
  content: string;
}

export interface Decision {
  decision: Verdict;
  payout: number;
  explanation: string;
  policy_section: string;
}

export interface ClaimDetail {
  claim_id: string;
  policy_id: string;
  customer_id: string;
  claim_type: string;
  submitted_on: string;
  incident_date: string;
  incident_location: string;
  summary: string;
  story: string;
  items: Item[];
  amount_claimed: number;
  documents: Document[];
  status: Status;
  decision: Decision | null;
  payment: { amount: number } | null;
}

export interface Policy {
  policy_id: string;
  plan: string;
  add_ons: string[];
  purchased_on: string;
  trip: {
    destination: string;
    departs_on: string;
    returns_on: string;
    trip_cost: number;
  };
  travelers: string[];
}

export interface PreviousClaim {
  claim_id: string;
  filed_on: string;
  claim_type: string;
  summary: string;
  outcome: string;
  amount_paid: number;
}

export interface Customer {
  customer_id: string;
  name: string;
  customer_since: string;
  previous_claims: PreviousClaim[];
}

export interface Step {
  /** The step's position, which holds because steps are only ever added. */
  id: number;
  kind: StepKind;
  text: string;
}

export interface SectionRead {
  document: "policy_wording" | "claims_manual";
  section: string;
  title: string;
}

export interface Todo {
  text: string;
  status: TodoStatus;
}

export interface Run {
  run_id: number;
  claim_limit: number;
  todos: Todo[];
  summary: string | null;
  finished: boolean;
}

export interface QueueView {
  claims: ClaimSummary[];
  run: Run | null;
}

export interface Instructions {
  queue: string;
  claim: string;
}

export interface ClaimView {
  claim: ClaimDetail;
  policy: Policy;
  customer: Customer;
  steps: Step[];
  reads: SectionRead[];
}

/** The same shape as the API sends it, with each amount a dollar string. */
type Wire<T, K extends keyof T> = Omit<T, K> & Record<K, string>;

type ClaimSummaryWire = Omit<ClaimSummary, "amount_claimed" | "payout"> & {
  amount_claimed: string;
  payout: string | null;
};

type ClaimDetailWire = Omit<
  ClaimDetail,
  "amount_claimed" | "items" | "decision" | "payment"
> & {
  amount_claimed: string;
  items: Wire<Item, "amount">[];
  decision: Wire<Decision, "payout"> | null;
  payment: { amount: string } | null;
};

type PolicyWire = Omit<Policy, "trip"> & {
  trip: Wire<Policy["trip"], "trip_cost">;
};

type CustomerWire = Omit<Customer, "previous_claims"> & {
  previous_claims: Wire<PreviousClaim, "amount_paid">[];
};

async function fetchOk(path: string): Promise<Response> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path} gave ${String(response.status)}`);
  return response;
}

async function get<T>(path: string): Promise<T> {
  return (await (await fetchOk(path)).json()) as T;
}

export async function fetchClaims(): Promise<ClaimSummary[]> {
  const claims = await get<ClaimSummaryWire[]>("/api/claims");
  return claims.map((claim) => ({
    ...claim,
    amount_claimed: toCents(claim.amount_claimed),
    payout: claim.payout === null ? null : toCents(claim.payout),
  }));
}

async function fetchClaim(claimId: string): Promise<ClaimDetail> {
  const claim = await get<ClaimDetailWire>(`/api/claims/${claimId}`);
  return {
    ...claim,
    amount_claimed: toCents(claim.amount_claimed),
    items: claim.items.map((item) => ({
      ...item,
      amount: toCents(item.amount),
    })),
    decision: claim.decision && {
      ...claim.decision,
      payout: toCents(claim.decision.payout),
    },
    payment: claim.payment && { amount: toCents(claim.payment.amount) },
  };
}

async function fetchPolicy(policyId: string): Promise<Policy> {
  const policy = await get<PolicyWire>(`/api/policies/${policyId}`);
  return {
    ...policy,
    trip: { ...policy.trip, trip_cost: toCents(policy.trip.trip_cost) },
  };
}

async function fetchCustomer(customerId: string): Promise<Customer> {
  const customer = await get<CustomerWire>(`/api/customers/${customerId}`);
  return {
    ...customer,
    previous_claims: customer.previous_claims.map((claim) => ({
      ...claim,
      amount_paid: toCents(claim.amount_paid),
    })),
  };
}

/** Load a claim with its policy, its customer and the agent's steps. */
export async function fetchClaimView(claimId: string): Promise<ClaimView> {
  const claim = await fetchClaim(claimId);
  const [policy, customer, steps, reads] = await Promise.all([
    fetchPolicy(claim.policy_id),
    fetchCustomer(claim.customer_id),
    get<Omit<Step, "id">[]>(`/api/claims/${claimId}/steps`),
    get<SectionRead[]>(`/api/claims/${claimId}/reads`),
  ]);
  return {
    claim,
    policy,
    customer,
    steps: steps.map((step, id) => ({ ...step, id })),
    reads,
  };
}

/** Load the queue with the latest run and its to-do list. */
export async function fetchQueueView(): Promise<QueueView> {
  const [claims, run] = await Promise.all([
    fetchClaims(),
    get<Run | null>("/api/runs/current"),
  ]);
  return { claims, run };
}

export async function fetchInstructions(): Promise<Instructions> {
  const [queue, claim] = await Promise.all([
    fetchOk("/api/instructions/queue").then((response) => response.text()),
    fetchOk("/api/instructions/claim").then((response) => response.text()),
  ]);
  return { queue, claim };
}
