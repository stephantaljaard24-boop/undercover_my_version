import { expect, test } from "@playwright/test";
import { decide, pay, signOff, startClaim, toldToTheAgent } from "./support";

test("a handler signs off a held payout and the agent is told", async ({
  page,
}) => {
  await startClaim("CLM-1020");
  await decide("CLM-1020", "approve", "1500.00");
  await page.goto("/#/claims/CLM-1020");
  await expect(
    page.getByText("Payment blocked: waiting for a handler's sign-off."),
  ).toBeVisible();

  await page.getByLabel("Sign off as").selectOption({ label: "Priya Raman" });
  await page.getByRole("button", { name: "Sign off" }).click();

  await expect(page.getByRole("heading", { name: /CLM-1020/ })).toContainText(
    "In progress",
  );
  await expect(page.getByText(/Signed off by Priya Raman on/)).toBeVisible();
  await expect.poll(toldToTheAgent).toContain("CLM-1020");

  expect(await pay("CLM-1020", "1500.00")).toBe(200);
  await expect(page.getByText("Paid $1,500.00.")).toBeVisible();
  await expect(page.getByText(/Signed off by Priya Raman on/)).toBeVisible();
  await expect(page.getByRole("heading", { name: /CLM-1020/ })).toContainText(
    "Decided",
  );
});

test("a second sign-off does not tell the agent again", async () => {
  await startClaim("CLM-1021");
  await decide("CLM-1021", "approve", "1200.00");
  await signOff("CLM-1021", "HND-01");
  await signOff("CLM-1021", "HND-02");
  await expect
    .poll(async () =>
      (await toldToTheAgent()).filter((id) => id === "CLM-1021"),
    )
    .toHaveLength(1);
});
