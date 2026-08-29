import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

/**
 * The partner site, end to end.
 *
 * These run against the live dev stack rather than mocks: the point is to
 * prove the three surfaces agree — the site, the API, and the database behind
 * it. A mocked panel would pass with a backend that returns nothing at all.
 *
 * Seeding goes through the admin dev login, which exists exactly for this and
 * is force-disabled outside development.
 */

// Serial on purpose. Every seeded partner files an application and signs in,
// and both endpoints sit behind the two-axis ip_guard, which counts per IP.
// Thirteen browsers doing that at once trip the throttle and the failures look
// like product bugs. Running them in order exercises the same paths without
// arguing with a protection that is working correctly.
test.describe.configure({ mode: "serial" });

const PARTNERS = process.env["PARTNERS_BASE_URL"] ?? "http://localhost:3003";
const API = process.env["API_BASE_URL"] ?? "http://localhost:8000";

const ADMIN_LOGIN = process.env["ADMIN_DEV_LOGIN"] ?? "devadmin";
const ADMIN_PASSWORD = process.env["ADMIN_DEV_PASSWORD"] ?? "devadmin-local-only";

/** A unique address per run, so reruns do not collide on UNIQUE(email). */
function freshEmail(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.floor(Math.random() * 1e6).toString(36)}@example.com`;
}

async function adminToken(request: APIRequestContext): Promise<string> {
  const res = await request.post(`${API}/api/v1/auth/admin-dev`, {
    data: { login: ADMIN_LOGIN, password: ADMIN_PASSWORD },
  });
  expect(res.ok(), "admin dev login must be enabled on the dev stack").toBeTruthy();
  const body = (await res.json()) as { access_token: string };
  return body.access_token;
}

interface SeededPartner {
  email: string;
  password: string;
  partnerId: string;
  code: string;
}

/**
 * Apply, approve, set a password and issue a code — the whole onboarding, done
 * through the API so a browser test can start from "a partner exists".
 */
async function seedPartner(request: APIRequestContext): Promise<SeededPartner> {
  const token = await adminToken(request);
  const auth = { Authorization: `Bearer ${token}` };
  const email = freshEmail("e2e-partner");
  const password = "e2e password long enough";

  const applied = await request.post(`${API}/api/v1/affiliate/applications`, {
    data: { email, display_name: "E2E Partner", channel: "t.me/e2e" },
  });
  expect(applied.status()).toBe(202);

  const queue = await request.get(`${API}/api/v1/admin/affiliate/applications`, {
    headers: auth,
  });
  expect(queue.ok()).toBeTruthy();
  const items = ((await queue.json()) as { items: { id: string; email: string }[] }).items;
  const row = items.find((i) => i.email === email);
  expect(row, "the application we just filed must be in the queue").toBeTruthy();
  const partnerId = row!.id;

  // The approval mints the set-password token. The API returns the partner
  // rather than the token — by design, since the token belongs in an email —
  // so the test asks the admin API to re-issue one it can use.
  const approved = await request.post(
    `${API}/api/v1/admin/affiliate/applications/${partnerId}/approve`,
    { headers: auth },
  );
  expect(approved.ok()).toBeTruthy();

  // The set-password link only ever reaches a partner by email, so the test
  // takes the same route an admin does when someone says it never arrived.
  const reinvite = await request.post(
    `${API}/api/v1/admin/affiliate/partners/${partnerId}/reinvite`,
    { headers: auth },
  );
  expect(reinvite.ok(), await reinvite.text()).toBeTruthy();
  const link = ((await reinvite.json()) as { link: string }).link;
  const setPasswordToken = new URL(link).searchParams.get("token");
  expect(setPasswordToken, "the reinvite link must carry a token").toBeTruthy();

  const set = await request.post(`${API}/api/v1/affiliate/auth/set-password`, {
    data: { token: setPasswordToken, password },
  });
  expect(set.status(), await set.text()).toBe(204);

  const code = `E2E${Math.floor(Math.random() * 1e6)
    .toString(36)
    .toUpperCase()}`;
  const issued = await request.post(`${API}/api/v1/admin/affiliate/partners/${partnerId}/codes`, {
    headers: auth,
    data: { code, discount_percent: "7", commission_percent: "2" },
  });
  expect(issued.status(), await issued.text()).toBe(201);

  return { email, password, partnerId, code: code.toUpperCase() };
}

test.describe("partner landing", () => {
  test("renders in all three locales", async ({ page }) => {
    for (const [path, marker] of [
      ["/", "Один код."],
      ["/en", "One code."],
      ["/uz", "Bitta kod."],
    ] as const) {
      await page.goto(`${PARTNERS}${path}`);
      await expect(page.getByRole("heading", { level: 1 })).toContainText(marker);
    }
  });

  test("answers the awkward questions before anyone signs up", async ({ page }) => {
    // The 14-day hold and the withdrawal floor are the two facts a partner
    // resents learning after joining. They have to be on the recruiting page.
    await page.goto(PARTNERS);
    const faq = page.getByText("14 дней", { exact: false });
    await expect(faq.first()).toBeVisible();
    await expect(page.getByText("50 000", { exact: false }).first()).toBeVisible();
  });

  test("the calculator responds to its inputs", async ({ page }) => {
    await page.goto(PARTNERS);
    const audience = page.locator('input[type="range"]').first();
    await expect(audience).toBeVisible();

    // The estimate lives next to its own label, so target that rather than
    // "any node containing a currency" — the page has several.
    const result = page.getByTestId("calc-result");
    const before = await result.textContent();

    await audience.fill("150000");

    await expect(async () => {
      expect(await result.textContent()).not.toBe(before);
    }).toPass({ timeout: 5_000 });
  });

  test("an application is accepted, and a repeat is answered identically", async ({ page }) => {
    const email = freshEmail("e2e-apply");
    for (const attempt of [1, 2]) {
      await page.goto(PARTNERS);
      await page.locator('input[name="email"]').fill(email);
      await page.locator('input[name="name"]').fill("Repeat Tester");
      await page.getByRole("button", { name: "Отправить" }).click();
      // Same success screen both times: telling someone "you already applied"
      // would let anyone with a list of addresses find the partners.
      await expect(page.getByText("Заявка принята")).toBeVisible({ timeout: 15_000 });
      expect(attempt).toBeLessThanOrEqual(2);
    }
  });
});

test.describe("partner authentication", () => {
  test("a wrong password says nothing about whether the account exists", async ({ page }) => {
    await page.goto(`${PARTNERS}/login`);
    await page.locator('input[name="email"]').fill("nobody-at-all@example.com");
    await page.locator('input[name="password"]').fill("definitely wrong");
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page.getByText("Неверный email или пароль")).toBeVisible({
      timeout: 15_000,
    });
  });

  test("the panel is closed to anyone without a session", async ({ page }) => {
    await page.goto(`${PARTNERS}/panel`);
    await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });
  });

  test("the set-password page explains itself without a token", async ({ page }) => {
    await page.goto(`${PARTNERS}/set-password`);
    await expect(page.getByText("Откройте ссылку из письма", { exact: false })).toBeVisible();
  });
});

/** Sign a seeded partner in through the form, like a person. */
async function signIn(page: Page, partner: SeededPartner): Promise<void> {
  await page.goto(`${PARTNERS}/login`);
  await page.locator('input[name="email"]').fill(partner.email);
  await page.locator('input[name="password"]').fill(partner.password);
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page).toHaveURL(/\/panel/, { timeout: 20_000 });
}

test.describe("the panel", () => {
  test("a partner signs in and sees an empty but working panel", async ({ page, request }) => {
    const partner = await seedPartner(request);
    await signIn(page, partner);

    // A brand-new partner has earned nothing. Zeroes are a legitimate state,
    // not an error, and the panel has to say so rather than break.
    await expect(page.getByText("Доступно к выводу")).toBeVisible();
    await expect(page.getByText("В удержании")).toBeVisible();
  });

  test("the labels say '30 days', never 'this month'", async ({ page, request }) => {
    // The API computes rolling windows. Calendar wording would be wrong every
    // day except the last one of the month.
    const partner = await seedPartner(request);
    await signIn(page, partner);

    await expect(page.getByText("за 30 дней")).toBeVisible();
    await expect(page.getByText("за 7 дней")).toBeVisible();
    await expect(page.getByText(/за месяц/)).toHaveCount(0);
  });

  test("the code page shows the issued code and both rates", async ({ page, request }) => {
    const partner = await seedPartner(request);
    await signIn(page, partner);

    await page.getByRole("link", { name: "Промокоды" }).click();
    await expect(page.getByText(partner.code)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Скидка покупателю")).toBeVisible();
    await expect(page.getByText("Ваша комиссия")).toBeVisible();
  });

  test("a partner with no earnings sees an explanation, not an empty table", async ({
    page,
    request,
  }) => {
    const partner = await seedPartner(request);
    await signIn(page, partner);

    await page.getByRole("link", { name: "Начисления" }).click();
    await expect(page.getByText("Начислений пока нет", { exact: false })).toBeVisible({
      timeout: 15_000,
    });
  });

  test("the payout form states the minimum and refuses below it", async ({ page, request }) => {
    const partner = await seedPartner(request);
    await signIn(page, partner);

    await page.getByRole("link", { name: "Выплаты" }).click();
    await expect(page.getByText("Минимум", { exact: false })).toBeVisible({ timeout: 15_000 });
    // Nothing is available yet, so the button must be disabled rather than
    // inviting a request that can only fail.
    await expect(page.getByRole("button", { name: "Заказать выплату" })).toBeDisabled();
  });

  test("signing out ends the session", async ({ page, request }) => {
    const partner = await seedPartner(request);
    await signIn(page, partner);

    await page.getByRole("button", { name: "Выйти" }).click();
    await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });

    // And the panel stays closed on a direct visit afterwards.
    await page.goto(`${PARTNERS}/panel`);
    await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });
  });
});
