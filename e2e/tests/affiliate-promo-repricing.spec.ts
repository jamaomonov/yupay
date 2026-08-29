import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

/**
 * What the promo field does when the cart changes underneath it.
 *
 * The field previews once, when the code is submitted, and stores the server's
 * totals. Nothing re-previews them. So the question this answers is whether a
 * buyer who applies a code and *then* picks a different package is shown a
 * price that is going to be charged.
 */

const WEB = process.env["WEB_BASE_URL"] ?? "http://localhost:3000";
const API = process.env["API_BASE_URL"] ?? "http://localhost:8000";
const ADMIN_LOGIN = process.env["ADMIN_DEV_LOGIN"] ?? "devadmin";
const ADMIN_PASSWORD = process.env["ADMIN_DEV_PASSWORD"] ?? "devadmin-local-only";
const COMPOSE_PROJECT = process.env["COMPOSE_PROJECT"] ?? "yupay-dev";

test.describe.configure({ mode: "serial" });

function unique(prefix: string): string {
  return `${prefix}${Date.now().toString(36)}${Math.floor(Math.random() * 1e4).toString(36)}`;
}

function sql(statement: string): string {
  return execFileSync(
    "docker",
    [
      "compose",
      "-p",
      COMPOSE_PROJECT,
      "exec",
      "-T",
      "postgres",
      "psql",
      "-U",
      "yupay_app",
      "-d",
      "yupay",
      "-A",
      "-t",
      "-c",
      statement,
    ],
    { encoding: "utf8", cwd: path.resolve(process.cwd(), "..") },
  ).trim();
}

async function adminToken(request: APIRequestContext): Promise<string> {
  const res = await request.post(`${API}/api/v1/auth/admin-dev`, {
    data: { login: ADMIN_LOGIN, password: ADMIN_PASSWORD },
  });
  expect(res.ok(), "the dev admin login must be enabled").toBeTruthy();
  return ((await res.json()) as { access_token: string }).access_token;
}

async function seedCode(request: APIRequestContext): Promise<string> {
  const auth = { Authorization: `Bearer ${await adminToken(request)}` };
  const email = `${unique("reprice-")}@example.com`;
  await request.post(`${API}/api/v1/affiliate/applications`, { data: { email } });
  const partnerId = sql(`select id from affiliate_partners where email = '${email}';`);
  await request.post(`${API}/api/v1/admin/affiliate/applications/${partnerId}/approve`, {
    headers: auth,
  });
  const code = unique("RPR").toUpperCase().slice(0, 10);
  const issued = await request.post(`${API}/api/v1/admin/affiliate/partners/${partnerId}/codes`, {
    headers: auth,
    data: { code, discount_percent: "10", commission_percent: "2" },
  });
  expect(issued.status(), await issued.text()).toBe(201);
  return code;
}

/** Register, verify and sign a buyer in through the storefront's own modal. */
async function signInBuyer(page: Page, request: APIRequestContext): Promise<void> {
  const email = `${unique("reprice-buyer-")}@example.com`;
  const password = "buyer password 123";
  const registered = await request.post(`${API}/api/v1/auth/register`, {
    data: { email, password },
  });
  expect(registered.ok(), await registered.text()).toBeTruthy();
  sql(`update users set email_verified_at = now() where email = '${email}';`);

  await page.getByRole("button", { name: "Войти" }).first().click();
  const modal = page.getByRole("dialog");
  await modal.getByRole("button", { name: "Email", exact: true }).click();
  await modal.locator('input[type="email"]').fill(email);
  await modal.locator('input[type="password"]').fill(password);
  await modal.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByRole("button", { name: "Войти" }).first()).toBeHidden({
    timeout: 30_000,
  });
}

test("changing the package after applying a code re-prices the discount", async ({
  page,
  request,
}) => {
  const code = await seedCode(request);

  // A brand with more than one package, so there is a second one to switch to.
  const brandSlug = sql(
    "select b.slug from brands b join products p on p.brand_id = b.id " +
      "join skus s on s.product_id = p.id and s.active " +
      "where b.active and p.active and coalesce(jsonb_array_length(p.required_fields), 0) = 0 " +
      "group by b.slug having count(s.id) > 1 limit 1;",
  );
  expect(brandSlug, "the dev catalog needs a field-free brand with two packages").toBeTruthy();

  await page.goto(`${WEB}/store/${brandSlug}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30_000 });
  await signInBuyer(page, request);

  const packs = page.locator('button, [role="button"]').filter({ hasText: /UZS/ });
  await packs.first().click();

  const promoInput = page.locator("#promo-code");
  await expect(promoInput).toBeVisible({ timeout: 30_000 });
  await promoInput.fill(code);
  await page.getByRole("button", { name: "Применить" }).click();
  await expect(page.getByTestId("promo-total-after")).toBeVisible({ timeout: 30_000 });

  const firstTotal = (await page.getByTestId("promo-total-after").textContent()) ?? "";
  expect(firstTotal.trim()).not.toBe("");

  // Now switch to a different package. The discount shown must follow the
  // cart — a checkout that displays the previous package's discounted total
  // is quoting a price nobody is going to be charged.
  await packs.nth(1).click();

  await expect(async () => {
    const after = (await page.getByTestId("promo-total-after").textContent()) ?? "";
    expect(after.trim(), "the discounted total must follow the selected package").not.toBe(
      firstTotal.trim(),
    );
  }).toPass({ timeout: 15_000 });
});

test("stepping back to the picker takes the Mini App discount with it", async ({
  page,
  request,
}) => {
  await page.setViewportSize({ width: 430, height: 932 });
  const code = await seedCode(request);

  const { createHmac } = await import("node:crypto");
  const tokenLine = execFileSync("grep", ["-m1", "^TELEGRAM_BOT_TOKEN=", ".env"], {
    encoding: "utf8",
    cwd: path.resolve(process.cwd(), ".."),
  }).trim();
  const botToken = tokenLine.split("=").slice(1).join("=");
  const fields: Record<string, string> = {
    user: JSON.stringify({ id: 870_000 + Math.floor(Math.random() * 90_000), first_name: "E2E" }),
    auth_date: String(Math.floor(Date.now() / 1000)),
  };
  const check = Object.keys(fields)
    .sort()
    .map((k) => `${k}=${fields[k] ?? ""}`)
    .join("\n");
  const secret = createHmac("sha256", "WebAppData").update(botToken).digest();
  const hash = createHmac("sha256", secret).update(check).digest("hex");
  const launch = new URLSearchParams({
    tgWebAppData: new URLSearchParams({ ...fields, hash }).toString(),
    tgWebAppVersion: "7.0",
    tgWebAppPlatform: "web",
    tgWebAppThemeParams: "{}",
  }).toString();

  const MINIAPP = process.env["MINIAPP_BASE_URL"] ?? "http://localhost:3001";
  await page.goto(`${MINIAPP}/topup/discord#${launch}`);

  const packs = page.locator("button").filter({ hasText: /UZS|сум/ });
  await expect(packs.first()).toBeVisible({ timeout: 30_000 });
  await packs.first().click();
  await page.getByTestId("btn-continue").click();

  const promo = page.locator("#promo-code");
  await expect(promo).toBeVisible({ timeout: 30_000 });
  await promo.fill(code);
  await page.getByRole("button", { name: "Применить" }).click();
  await expect(page.getByTestId("promo-applied")).toBeVisible({ timeout: 30_000 });
  const discounted = (await page.getByTestId("btn-pay").textContent()) ?? "";

  // Back to the picker, choose a different package, forward again.
  await page.getByRole("button", { name: "Назад" }).click();
  await expect(packs.first()).toBeVisible({ timeout: 30_000 });
  await packs.nth(1).click();
  await page.getByTestId("btn-continue").click();
  await expect(page.getByTestId("btn-pay")).toBeVisible({ timeout: 30_000 });

  const nowShown = (await page.getByTestId("btn-pay").textContent()) ?? "";
  expect(nowShown.trim(), "the pay button must not keep the old package's discount").not.toBe(
    discounted.trim(),
  );
});

test("the promo field is offered before any package is chosen", async ({ page, request }) => {
  // A buyer holding a code should be able to see this checkout takes one
  // without first committing to a package. The field cannot price an empty
  // cart, so it says what it is waiting for rather than sitting there dead.
  const brandSlug = sql(
    "select b.slug from brands b join products p on p.brand_id = b.id " +
      "join skus s on s.product_id = p.id and s.active " +
      "where b.active and p.active and coalesce(jsonb_array_length(p.required_fields), 0) = 0 " +
      "group by b.slug having count(s.id) > 1 limit 1;",
  );
  await page.goto(`${WEB}/store/${brandSlug}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30_000 });
  await signInBuyer(page, request);

  const promoInput = page.locator("#promo-code");
  await expect(promoInput).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Сначала выберите пакет")).toBeVisible();
  await promoInput.fill("ANYCODE");
  await expect(page.getByRole("button", { name: "Применить" })).toBeDisabled();

  await promoInput.scrollIntoViewIfNeeded();
  await page.screenshot({ path: "journey/promo-before-package.png" });

  // Choosing a package is all it takes.
  await page.locator('button, [role="button"]').filter({ hasText: /UZS/ }).first().click();
  await expect(page.getByRole("button", { name: "Применить" })).toBeEnabled({ timeout: 15_000 });
  await expect(page.getByText("Сначала выберите пакет")).toBeHidden();
});
