import { toCents } from "./money";

export type Status =
  "waiting" | "in_progress" | "awaiting_sign_off" | "decided";
export type Verdict = "approve" | "decline" | "refer";

/** A claim in the queue. Amounts are whole cents. */
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

type ClaimSummaryWire = Omit<ClaimSummary, "amount_claimed" | "payout"> & {
  amount_claimed: string;
  payout: string | null;
};

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`${path} gave ${String(response.status)}`);
  return (await response.json()) as T;
}

export async function fetchClaims(): Promise<ClaimSummary[]> {
  const claims = await get<ClaimSummaryWire[]>("/api/claims");
  return claims.map((claim) => ({
    ...claim,
    amount_claimed: toCents(claim.amount_claimed),
    payout: claim.payout === null ? null : toCents(claim.payout),
  }));
}
