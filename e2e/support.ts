const API = "http://127.0.0.1:8001/api";

async function post(path: string, body?: object): Promise<void> {
  const response = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body && JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${path} gave ${String(response.status)}`);
}

/** How many claims are in each status, from the API. */
export async function countByStatus(): Promise<Record<string, number>> {
  const response = await fetch(`${API}/claims`);
  const claims = (await response.json()) as { status: string }[];
  const counts: Record<string, number> = {};
  for (const { status } of claims) counts[status] = (counts[status] ?? 0) + 1;
  return counts;
}

export async function startClaim(claimId: string): Promise<void> {
  await post(`/claims/${claimId}/start`);
}

export async function addStep(
  claimId: string,
  kind: "tool_call" | "tool_result" | "reply",
  text: string,
): Promise<void> {
  await post(`/claims/${claimId}/steps`, { kind, text });
}

/** Record a made-up decision, which is not one of the handlers' answers. */
export async function decide(
  claimId: string,
  decision: "approve" | "decline" | "refer",
  payout: string,
): Promise<void> {
  await post(`/claims/${claimId}/decision`, {
    decision,
    payout,
    explanation: "A made-up decision for a test.",
    policy_section: "3. Trip Delay",
  });
}

/** Try to pay a claim and return the status code the backend answered with. */
export async function pay(claimId: string, amount: string): Promise<number> {
  const response = await fetch(`${API}/claims/${claimId}/payment`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ amount }),
  });
  return response.status;
}
