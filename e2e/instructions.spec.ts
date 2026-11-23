import { expect, test } from "@playwright/test";

test("the instructions page shows what the agent is told", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Instructions" }).click();
  await expect(page).toHaveURL(/#\/instructions$/);
  await expect(
    page.getByRole("heading", { name: "Agent instructions" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Running the queue" }),
  ).toBeVisible();
  await expect(
    page.getByText("You do not decide claims yourself"),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Working a claim" }),
  ).toBeVisible();
  await expect(page.getByText("Accuse a customer of dishonesty")).toBeVisible();
});
