import { expect, test } from "@playwright/test";

test("home page renders YuPay brand", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "YuPay" })).toBeVisible();
});

test("ping page receives API smoke payload", async ({ page }) => {
  await page.goto("/ping");
  await expect(page.getByText(/"module": "catalog"/)).toBeVisible();
  await expect(page.getByText(/"status": "ok"/)).toBeVisible();
});
