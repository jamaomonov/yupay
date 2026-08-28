import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

/**
 * The three admin screens, opened in a browser.
 *
 * They were built against the API and never looked at. That is the gap this
 * closes: the same gap on the storefront hid a promo field that sent no
 * Authorization header and told every buyer their perfectly good code was
 * invalid, while every unit test passed.
 *
 * Serial, and one worker — the seeding endpoints sit behind the two-axis
 * `ip_guard`, which counts per IP.
 */

const ADMIN = process.env["ADMIN_BASE_URL"] ?? "http://localhost:3002";
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

async function apiToken(request: APIRequestContext): Promise<string> {
  const res = await request.post(`${API}/api/v1/auth/admin-dev`, {
    data: { login: ADMIN_LOGIN, password: ADMIN_PASSWORD },
  });
  expect(res.ok(), "the dev admin login must be enabled").toBeTruthy();
  return ((await res.json()) as { access_token: string }).access_token;
}

/** Sign in to the admin SPA through its own form. */
async function signIn(page: Page): Promise<void> {
  await page.goto(`${ADMIN}/login`);
  await page.locator('input[placeholder="admin"]').fill(ADMIN_LOGIN);
  await page.locator('input[type="password"]').fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page).not.toHaveURL(/\/login/, { timeout: 30_000 });
}

test("the application queue lists a new applicant and approves them", async ({ page, request }) => {
  const email = `${unique("admin-e2e-")}@example.com`;
  const applied = await request.post(`${API}/api/v1/affiliate/applications`, {
    data: { email, display_name: "Admin E2E", channel: "t.me/admin-e2e" },
  });
  expect(applied.status()).toBe(202);

  await signIn(page);
  await page.goto(`${ADMIN}/affiliate/applications`);

  await expect(page.getByText(email).first()).toBeVisible({ timeout: 30_000 });

  await page
    .locator("tr")
    .filter({ hasText: email })
    .getByRole("button", { name: "Одобрить" })
    .click();

  // Gone from the queue, which only lists pending applications.
  await expect(page.getByText(email).first()).toBeHidden({ timeout: 30_000 });

  const status = sql(`select status from affiliate_partners where email = '${email}';`);
  expect(status).toBe("active");
});

test("an application can be turned down with a reason", async ({ page, request }) => {
  const email = `${unique("admin-rej-")}@example.com`;
  const filed = await request.post(`${API}/api/v1/affiliate/applications`, {
    data: { email },
  });
  expect(filed.status(), await filed.text()).toBe(202);

  await signIn(page);
  await page.goto(`${ADMIN}/affiliate/applications`);
  await expect(page.getByText(email).first()).toBeVisible({ timeout: 30_000 });

  const row = page.locator("tr").filter({ hasText: email });
  await row.locator('input[placeholder="Причина отказа"]').fill("аудитория не подходит");
  await row.getByRole("button", { name: "Отклонить" }).click();

  await expect(page.getByText(email).first()).toBeHidden({ timeout: 30_000 });
  expect(sql(`select status from affiliate_partners where email = '${email}';`)).toBe("rejected");
  expect(sql(`select admin_note from affiliate_partners where email = '${email}';`)).toBe(
    "аудитория не подходит",
  );
});

test("a code is issued from the partners screen, with its ranges on screen", async ({
  page,
  request,
}) => {
  const email = `${unique("admin-code-")}@example.com`;
  const token = await apiToken(request);
  const auth = { Authorization: `Bearer ${token}` };

  await request.post(`${API}/api/v1/affiliate/applications`, { data: { email } });
  const partnerId = sql(`select id from affiliate_partners where email = '${email}';`);
  await request.post(`${API}/api/v1/admin/affiliate/applications/${partnerId}/approve`, {
    headers: auth,
  });

  await signIn(page);
  await page.goto(`${ADMIN}/affiliate/partners`);
  const row = page.locator("tr").filter({ hasText: email });
  await expect(row).toBeVisible({ timeout: 30_000 });

  await row.getByRole("button", { name: "Выдать код" }).click();

  // The allowed ranges are on screen before anything is typed, rather than
  // being discovered by being rejected.
  await expect(page.getByText("Скидка 3–10%")).toBeVisible();
  await expect(page.getByText("Комиссия 1–2%")).toBeVisible();

  const code = unique("ADM").toUpperCase().slice(0, 10);
  await row.locator('input[placeholder="PARTNER10"]').fill(code);
  await row.getByRole("button", { name: "Выдать" }).click();

  await expect(page.getByText(`Код ${code} выдан`)).toBeVisible({ timeout: 30_000 });
  expect(sql(`select code from affiliate_codes where code = '${code}';`)).toBe(code);
});

test("the payout queue masks the card and the detail view reveals it", async ({
  page,
  request,
}) => {
  const email = `${unique("admin-pay-")}@example.com`;
  const card = "8600555544443333";
  const token = await apiToken(request);
  const auth = { Authorization: `Bearer ${token}` };

  await request.post(`${API}/api/v1/affiliate/applications`, { data: { email } });
  const partnerId = sql(`select id from affiliate_partners where email = '${email}';`);
  await request.post(`${API}/api/v1/admin/affiliate/applications/${partnerId}/approve`, {
    headers: auth,
  });
  sql(
    `insert into affiliate_payouts (id, partner_id, amount, currency, card_number, card_holder, status, created_at)
     values (gen_random_uuid(), '${partnerId}', 100000, 'UZS', '${card}', 'ADMIN E2E', 'requested', now());`,
  );

  await signIn(page);
  await page.goto(`${ADMIN}/affiliate/payouts`);

  const row = page.locator("tr").filter({ hasText: email });
  await expect(row).toBeVisible({ timeout: 30_000 });

  // The queue is what an admin has open all day and might screenshot.
  await expect(page.getByText(card)).toHaveCount(0);
  await expect(row.getByText(`···· ${card.slice(-4)}`)).toBeVisible();

  // The detail view is opened deliberately, at the moment a transfer is about
  // to be typed into a banking app. That is the one place the number appears.
  await row.getByRole("button", { name: "Открыть" }).click();
  await expect(page.getByText(card).first()).toBeVisible({ timeout: 30_000 });
});

test("marking a payout paid asks first, and says it cannot be undone", async ({
  page,
  request,
}) => {
  const email = `${unique("admin-paid-")}@example.com`;
  const token = await apiToken(request);
  const auth = { Authorization: `Bearer ${token}` };

  await request.post(`${API}/api/v1/affiliate/applications`, { data: { email } });
  const partnerId = sql(`select id from affiliate_partners where email = '${email}';`);
  await request.post(`${API}/api/v1/admin/affiliate/applications/${partnerId}/approve`, {
    headers: auth,
  });
  // A balance to draw on, and a request against it.
  sql(
    `insert into affiliate_payouts (id, partner_id, amount, currency, card_number, card_holder, status, created_at)
     values (gen_random_uuid(), '${partnerId}', 100000, 'UZS', '8600111122223333', 'PAID E2E', 'requested', now());`,
  );

  await signIn(page);
  await page.goto(`${ADMIN}/affiliate/payouts`);
  const row = page.locator("tr").filter({ hasText: email });
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.getByRole("button", { name: "Открыть" }).click();

  // The only irreversible action in the programme, so it confirms — and the
  // confirmation says why rather than asking "are you sure".
  let asked = "";
  page.once("dialog", (dialog) => {
    asked = dialog.message();
    void dialog.dismiss();
  });
  await page.getByRole("button", { name: "Выплачено" }).click();
  await expect.poll(() => asked, { timeout: 10_000 }).toContain("необратимо");

  // Dismissed, so nothing moved.
  expect(sql(`select status from affiliate_payouts where partner_id = '${partnerId}';`)).toBe(
    "requested",
  );
});
