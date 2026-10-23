import { expect, test } from "@playwright/test";

test("the instructions page shows what the agent is told", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "Instructions" }).click();
  await expect(page).toHaveURL(/#\/instructions$/);
  await expect(
    page.getByRole("heading", { name: "Agent instructions" }),
  ).toBeVisible();
  await expect(page.getByText("You are the UnderCover Agent")).toBeVisible();
  await expect(page.getByText("Work it out as section 10")).toBeVisible();
});
