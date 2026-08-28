import { createHmac } from "node:crypto";
import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type APIRequestContext } from "@playwright/test";

/**
 * The promo field on the Mini App checkout.
 *
 * Worth its own file because the Mini App authenticates from Telegram
 * `initData` and nothing else — outside the Telegram client the app boots
 * anonymous, and the interesting path (a signed-in buyer applying a code) is
 * unreachable without one.
 *
 * So the test signs its own. The scheme is public — HMAC-SHA256 keyed by
 * HMAC("WebAppData", botToken) over the sorted `k=v` pairs — and the dev bot
 * token is in `.env`, which is the same thing the backend's integration tests
 * do. A minimal `window.Telegram.WebApp` is injected before the bundle runs,
 * because `lib/telegram.ts` reads it synchronously on mount.
 *
 * This mirrors the web spec deliberately: the web version of this field
 * shipped sending no Authorization header, and every unit test passed because
 * they all stub fetch. Only a browser against a real API catches that, and
 * this surface deserves the same check.
 */

const MINIAPP = process.env["MINIAPP_BASE_URL"] ?? "http://localhost:3001";
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

/** The dev bot token, read the way the stack reads it. */
function botToken(): string {
  const env = execFileSync("grep", ["-m1", "^TELEGRAM_BOT_TOKEN=", ".env"], {
    encoding: "utf8",
    cwd: path.resolve(process.cwd(), ".."),
  }).trim();
  const token = env.split("=").slice(1).join("=");
  expect(token, "TELEGRAM_BOT_TOKEN must be set in .env").toBeTruthy();
  return token;
}

/** Telegram's own signing scheme, applied to a made-up user. */
function signInitData(tgId: number): string {
  const fields: Record<string, string> = {
    user: JSON.stringify({ id: tgId, first_name: "E2E" }),
    auth_date: String(Math.floor(Date.now() / 1000)),
  };
  const check = Object.keys(fields)
    .sort()
    .map((k) => `${k}=${fields[k] ?? ""}`)
    .join("\n");
  const secret = createHmac("sha256", "WebAppData").update(botToken()).digest();
  const hash = createHmac("sha256", secret).update(check).digest("hex");
  return new URLSearchParams({ ...fields, hash }).toString();
}

async function adminToken(request: APIRequestContext): Promise<string> {
  const res = await request.post(`${API}/api/v1/auth/admin-dev`, {
    data: { login: ADMIN_LOGIN, password: ADMIN_PASSWORD },
  });
  expect(res.ok(), "the dev admin login must be enabled").toBeTruthy();
  return ((await res.json()) as { access_token: string }).access_token;
}

/** An approved partner with a live code. Returns the code. */
async function seedCode(request: APIRequestContext): Promise<string> {
  const auth = { Authorization: `Bearer ${await adminToken(request)}` };
  const email = `${unique("mini-")}@example.com`;
  const applied = await request.post(`${API}/api/v1/affiliate/applications`, {
    data: { email },
  });
  expect(applied.status()).toBe(202);

  const partnerId = sql(`select id from affiliate_partners where email = '${email}';`);
  const approved = await request.post(
    `${API}/api/v1/admin/affiliate/applications/${partnerId}/approve`,
    { headers: auth },
  );
  expect(approved.ok(), await approved.text()).toBeTruthy();

  const code = unique("MINI").toUpperCase().slice(0, 12);
  const issued = await request.post(`${API}/api/v1/admin/affiliate/partners/${partnerId}/codes`, {
    headers: auth,
    data: { code, discount_percent: "8", commission_percent: "2" },
  });
  expect(issued.status(), await issued.text()).toBe(201);
  return code;
}

test("a signed-in Mini App buyer applies a code and sees the discount", async ({
  page,
  request,
}) => {
  // A phone-shaped viewport, because the Mini App only ever runs in one. The
  // action bar at the bottom is fixed, so a `fullPage` shot composites it over
  // the package grid and shows a layout nobody will ever see.
  await page.setViewportSize({ width: 430, height: 932 });

  const code = await seedCode(request);
  const initData = signInitData(880_000 + Math.floor(Math.random() * 90_000));

  // Handed over the way a real Telegram client does it: the launch params ride
  // the URL fragment and telegram-web-app.js reads them from there. No fake
  // globals, so what boots is the same code path a phone runs.
  const launch = new URLSearchParams({
    tgWebAppData: initData,
    tgWebAppVersion: "7.0",
    tgWebAppPlatform: "web",
    tgWebAppThemeParams: "{}",
  }).toString();
  await page.goto(`${MINIAPP}/#${launch}`);
  // Booted and authenticated from initData rather than falling through to the
  // anonymous path — otherwise the promo field would only ever show its
  // sign-in branch and this would prove nothing.
  await expect(page.locator("body")).not.toContainText("Откройте приложение через Telegram", {
    timeout: 30_000,
  });

  // Roblox rather than a game top-up: it is a voucher, so it asks for no
  // account id and the review screen is one click away. A product with a
  // required field would need its validator to answer first, which is a
  // different feature's problem.
  await page.goto(`${MINIAPP}/topup/roblox#${launch}`);

  const pack = page
    .locator("button")
    .filter({ hasText: /UZS|сум/ })
    .first();
  await expect(pack).toBeVisible({ timeout: 30_000 });
  await pack.click();

  // The promo field lives on the review screen, under the payment method and
  // above the pay button — the same order the storefront uses.
  await page.getByTestId("btn-continue").click();
  await expect(page.getByTestId("btn-pay")).toBeVisible({ timeout: 30_000 });

  const promo = page.locator("#promo-code");
  await expect(promo).toBeVisible({ timeout: 30_000 });
  await promo.fill(code);
  await page.getByRole("button", { name: "Применить" }).click();

  // The same property as the web field: the old total struck through beside
  // the new one, both from the server.
  await expect(page.getByText(code)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Вы экономите", { exact: false })).toBeVisible();

  // The field belongs above the button whose price it changes — it shipped
  // below it, which no assertion here would have caught.
  const field = page.locator('#promo-code, [data-testid="promo-applied"]').first();
  const button = page.getByTestId("btn-continue").or(page.getByTestId("btn-pay")).first();
  const fieldBox = await field.boundingBox();
  const buttonBox = await button.boundingBox();
  expect(fieldBox, "the promo field must be on screen").toBeTruthy();
  expect(buttonBox, "the action button must be on screen").toBeTruthy();
  expect(fieldBox!.y, "the promo field sits above the action button").toBeLessThan(buttonBox!.y);

  // One frame, beside the journey's, so the Mini App's version of this can be
  // looked at rather than only asserted.
  await page.screenshot({ path: "journey/miniapp-promo-applied.png" });
});
