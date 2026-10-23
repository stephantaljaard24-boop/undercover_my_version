import { expect, test } from "@playwright/test";
import { addStep, decide, pay, startClaim } from "./support";

test("a claim in progress shows its steps as the agent works", async ({
  page,
}) => {
  await startClaim("CLM-1011");
  await addStep("CLM-1011", "tool_call", 'get_claim {"claim_id": "CLM-1011"}');
  await page.goto("/#/claims/CLM-1011");

  await expect(page.getByRole("heading", { name: /CLM-1011/ })).toContainText(
    "In progress",
  );
  await expect(
    page.getByText("The agent is working on this claim."),
  ).toBeVisible();
  await expect(
    page.getByText('get_claim {"claim_id": "CLM-1011"}'),
  ).toBeVisible();

  await addStep("CLM-1011", "tool_result", "A made-up result");
  await expect(page.getByText("A made-up result")).toBeVisible();
});

test("a claim is shown in full", async ({ page }) => {
  await page.goto("/#/claims/CLM-1001");
  await expect(page.getByText("My flight home from Rome")).toBeVisible();
  await expect(page.getByText("Airport hotel, one night")).toBeVisible();
  await expect(
    page.getByText("Meridian Air cancellation notice"),
  ).toBeVisible();
  await expect(
    page.getByText("Hotel Aurelia Fiumicino. Guest: Maya Patel"),
  ).toBeVisible();
  await expect(page.getByText("Total claimed")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Policy" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Customer" })).toBeVisible();
});

test("a decided and paid claim shows its decision and payment", async ({
  page,
}) => {
  await startClaim("CLM-1012");
  await decide("CLM-1012", "approve", "420.00");
  expect(await pay("CLM-1012", "420.00")).toBe(200);
  await page.goto("/#/claims/CLM-1012");

  await expect(page.getByRole("heading", { name: /CLM-1012/ })).toContainText(
    "Decided",
  );
  await expect(page.getByText("A made-up decision for a test.")).toBeVisible();
  await expect(page.getByText("Policy section: 3. Trip Delay")).toBeVisible();
  await expect(page.getByText("Paid $420.00.")).toBeVisible();
});

test("a payout over the limit shows its payment blocked", async ({ page }) => {
  await startClaim("CLM-1013");
  await decide("CLM-1013", "approve", "1500.00");
  expect(await pay("CLM-1013", "1500.00")).toBe(403);
  await page.goto("/#/claims/CLM-1013");

  await expect(page.getByRole("heading", { name: /CLM-1013/ })).toContainText(
    "Waiting for sign-off",
  );
  await expect(
    page.getByText("Payment blocked: waiting for a handler's sign-off."),
  ).toBeVisible();
  await expect(page.getByText("Paid $")).toHaveCount(0);
});
