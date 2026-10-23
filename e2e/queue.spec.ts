import { expect, test } from "@playwright/test";
import { countByStatus, decide, pay, startClaim } from "./support";

test("each claim shows where it stands, and the counts add up", async ({
  page,
}) => {
  await startClaim("CLM-1001");
  await startClaim("CLM-1002");
  await decide("CLM-1002", "approve", "420.00");
  expect(await pay("CLM-1002", "420.00")).toBe(200);
  await startClaim("CLM-1003");
  await decide("CLM-1003", "approve", "1500.00");
  expect(await pay("CLM-1003", "1500.00")).toBe(403);
  await startClaim("CLM-1004");
  await decide("CLM-1004", "decline", "0.00");

  await page.goto("/");
  await expect(page.getByRole("row")).toHaveCount(26);
  const row = (id: string) => page.getByRole("row", { name: new RegExp(id) });
  await expect(row("CLM-1001")).toContainText("In progress");
  await expect(row("CLM-1002")).toContainText("Decided");
  await expect(row("CLM-1002")).toContainText("Approved $420.00");
  await expect(row("CLM-1003")).toContainText("Waiting for sign-off");
  await expect(row("CLM-1003")).toContainText("Approved $1,500.00");
  await expect(row("CLM-1004")).toContainText("Declined");
  await expect(row("CLM-1025")).toContainText("Waiting");

  const counts = await countByStatus();
  const region = page.getByRole("region", { name: "Claims by status" });
  const expected = {
    Waiting: counts.waiting,
    "In progress": counts.in_progress,
    "Waiting for sign-off": counts.awaiting_sign_off,
    Decided: counts.decided,
  };
  for (const [label, count] of Object.entries(expected)) {
    await expect(
      region.getByText(label, { exact: true }).locator(".."),
    ).toHaveText(`${String(count)}${label}`);
  }
});

test("a row opens its claim", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "CLM-1010" }).click();
  await expect(page).toHaveURL(/#\/claims\/CLM-1010$/);
});
