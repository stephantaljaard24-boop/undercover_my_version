import { expect, test } from "@playwright/test";
import {
  countByStatus,
  decide,
  failClaim,
  finishRun,
  pay,
  setTodos,
  startClaim,
  startRun,
} from "./support";

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
  for (let attempt = 0; attempt < 2; attempt++) {
    await startClaim("CLM-1005");
    await failClaim("CLM-1005", "A made-up failure");
  }

  await page.goto("/");
  await expect(page.getByRole("row")).toHaveCount(26);
  const row = (id: string) => page.getByRole("row", { name: new RegExp(id) });
  await expect(row("CLM-1001")).toContainText("In progress");
  await expect(row("CLM-1002")).toContainText("Decided");
  await expect(row("CLM-1002")).toContainText("Approved $420.00");
  await expect(row("CLM-1003")).toContainText("Waiting for sign-off");
  await expect(row("CLM-1003")).toContainText("Approved $1,500.00");
  await expect(row("CLM-1004")).toContainText("Declined");
  await expect(row("CLM-1005")).toContainText("Left for a handler");
  await expect(row("CLM-1025")).toContainText("Waiting");

  const counts = await countByStatus();
  const region = page.getByRole("region", { name: "Claims by status" });
  const expected = {
    Waiting: counts.waiting,
    "In progress": counts.in_progress,
    "Waiting for sign-off": counts.awaiting_sign_off,
    Decided: counts.decided,
    "Left for a handler": counts.needs_handler,
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

test("the current run shows its to-do list as it is ticked off", async ({
  page,
}) => {
  const runId = await startRun(3, [
    { text: "CLM-1020 first", status: "in_progress" },
    { text: "CLM-1021 second", status: "todo" },
    { text: "CLM-1022 third", status: "left_for_handler" },
  ]);
  await page.goto("/");

  const run = page.getByRole("region", { name: "Current run" });
  await expect(run).toContainText("Up to 3 claims. Running.");
  const item = (text: string) =>
    run.getByRole("listitem").filter({ hasText: text });
  await expect(item("CLM-1020")).toContainText("In progress");
  await expect(item("CLM-1021")).toContainText("To do");
  await expect(item("CLM-1022")).toContainText("Left for a handler");

  await setTodos(runId, [
    { text: "CLM-1020 first", status: "done" },
    { text: "CLM-1021 second", status: "todo" },
    { text: "CLM-1022 third", status: "left_for_handler" },
  ]);
  await expect(item("CLM-1020")).toContainText("Done");

  await finishRun(runId, "A made-up summary for a test.");
  await expect(run).toContainText("Finished.");
  await expect(run.getByText("A made-up summary for a test.")).toBeVisible();
});
