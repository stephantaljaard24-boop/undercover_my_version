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
  kind: "tool_call" | "tool_result" | "reply" | "error",
  text: string,
): Promise<void> {
  await post(`/claims/${claimId}/steps`, { kind, text });
}

/** Fail a claim that is in progress, as the agent does when something breaks. */
export async function failClaim(
  claimId: string,
  reason: string,
): Promise<void> {
  await post(`/claims/${claimId}/fail`, { reason });
}

export async function addRead(
  claimId: string,
  document: "policy_wording" | "claims_manual",
  section: string,
): Promise<void> {
  await post(`/claims/${claimId}/reads`, { document, section });
}

export interface Todo {
  text: string;
  status: "todo" | "in_progress" | "done" | "left_for_handler";
}

/** Start a run, set its to-do list and return its id. */
export async function startRun(
  claimLimit: number,
  todos: Todo[],
): Promise<number> {
  const response = await fetch(`${API}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ claim_limit: claimLimit }),
  });
  const { run_id: runId } = (await response.json()) as { run_id: number };
  await setTodos(runId, todos);
  return runId;
}

export async function setTodos(runId: number, todos: Todo[]): Promise<void> {
  await fetch(`${API}/runs/${String(runId)}/todos`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ todos }),
  });
}

export async function finishRun(runId: number, summary: string): Promise<void> {
  await post(`/runs/${String(runId)}/finish`, { summary });
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
