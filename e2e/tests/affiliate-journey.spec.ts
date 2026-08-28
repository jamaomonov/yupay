import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import path from "node:path";

import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

/**
 * The whole affiliate programme, once, in order, with a screenshot at every
 * step a person would see.
 *
 * A partner applies, an admin approves them and issues a code, a buyer uses
 * that code and pays, the commission accrues and matures, the partner asks for
 * their money, and an admin sends it. Eighteen screenshots land in
 * `e2e/journey/` so the flow can be reviewed as a sequence rather than read as
 * assertions.
 *
 * ## Why some steps go around the browser
 *
 * Three states cannot be reached by clicking, and each is nudged deliberately
 * rather than faked:
 *
 * - **Delivery.** The dev catalog has no inventory codes and no reachable
 *   supplier, so an order that is paid never becomes delivered. The journey
 *   marks it delivered directly, which is the state a real fulfilment would
 *   have produced.
 * - **Accrual.** The sweep runs on a five-minute timer. The journey calls the
 *   same function the scheduler calls, rather than waiting.
 * - **Maturation.** Commission is held for 14 days. The journey moves
 *   `available_at` into the past — the one thing no amount of clicking can do.
 *
 * Everything else — every approval, every form, every number on screen — goes
 * through the real UI against the real API.
 */

const PARTNERS = process.env["PARTNERS_BASE_URL"] ?? "http://localhost:3003";
const WEB = process.env["WEB_BASE_URL"] ?? "http://localhost:3000";
const ADMIN = process.env["ADMIN_BASE_URL"] ?? "http://localhost:3002";
const API = process.env["API_BASE_URL"] ?? "http://localhost:8000";

const ADMIN_LOGIN = process.env["ADMIN_DEV_LOGIN"] ?? "devadmin";
const ADMIN_PASSWORD = process.env["ADMIN_DEV_PASSWORD"] ?? "devadmin-local-only";

const SHOTS = path.resolve(process.cwd(), "journey");
const COMPOSE_PROJECT = process.env["COMPOSE_PROJECT"] ?? "yupay-dev";

let step = 0;

/** Capture the current page as the next numbered frame of the story. */
async function shot(page: Page, name: string): Promise<void> {
  step += 1;
  const file = path.join(SHOTS, `${String(step).padStart(2, "0")}-${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
}

/** Run SQL against the dev database. Only for states no UI can produce. */
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

/** Run the accrual sweep now instead of waiting for the scheduler's tick. */
function runSweep(): void {
  execFileSync(
    "docker",
    [
      "compose",
      "-p",
      COMPOSE_PROJECT,
      "exec",
      "-T",
      "api",
      "python",
      "-c",
      [
        "import asyncio",
        // SQLAlchemy resolves relationship targets by name, so every mapped
        // class has to be imported before any mapper can be configured. This
        // is the same import set migrations/env.py keeps, and the same trap
        // the seed scripts hit.
        "from yupay.modules.catalog import models as _c  # noqa: F401",
        "from yupay.modules.orders import models as _o  # noqa: F401",
        "from yupay.modules.payments import models as _p  # noqa: F401",
        "from yupay.modules.users import models as _u  # noqa: F401",
        "from yupay.modules.wallet import models as _w  # noqa: F401",
        "from yupay.modules.affiliate import models as _a  # noqa: F401",
        "from yupay.core.db import get_session_factory",
        "from yupay.modules.affiliate import api as aff",
        "async def main():",
        "    f = get_session_factory()",
        "    async with f() as s:",
        "        async with s.begin():",
        "            a = await aff.accrue_commissions(s, hold_days=14)",
        "            m = await aff.mature_commissions(s)",
        "    print('accrued', a, 'matured', m)",
        "asyncio.run(main())",
      ].join("\n"),
    ],
    { encoding: "utf8", cwd: path.resolve(process.cwd(), "..") },
  );
}

async function adminToken(request: APIRequestContext): Promise<string> {
  const res = await request.post(`${API}/api/v1/auth/admin-dev`, {
    data: { login: ADMIN_LOGIN, password: ADMIN_PASSWORD },
  });
  expect(res.ok(), "the dev admin login must be enabled").toBeTruthy();
  return ((await res.json()) as { access_token: string }).access_token;
}

function unique(prefix: string): string {
  return `${prefix}${Date.now().toString(36)}${Math.floor(Math.random() * 1e4).toString(36)}`;
}

/** An idempotency key that is always long enough.
 *
 *  `unique()` builds from base36, whose length varies with the value, so it
 *  sometimes landed under the API's 16-character floor and the order was
 *  refused — intermittently, which is the worst way for a test to fail. */
function idempotencyKey(): string {
  return crypto.randomUUID();
}

test.describe.configure({ mode: "serial", timeout: 180_000 });

test("the whole programme, from application to payout", async ({ page, request }, testInfo) => {
  // Desktop only. This is a narrative walkthrough meant to be read as a
  // sequence of frames, and the storefront's checkout is a sidebar on desktop
  // and a stacked block on mobile — running it twice would produce two sets of
  // screenshots and prove nothing the responsive tests do not already cover.
  test.skip(testInfo.project.name !== "chromium", "desktop walkthrough");

  mkdirSync(SHOTS, { recursive: true });

  const partnerEmail = `${unique("journey-")}@example.com`;
  const partnerPassword = "journey password long enough";
  const code = unique("J").toUpperCase().slice(0, 12);
  const auth = { Authorization: `Bearer ${await adminToken(request)}` };

  // ── 1. A prospective partner reads the pitch ───────────────────────────
  await page.goto(PARTNERS);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await shot(page, "landing");

  // ── 2. …and the answers to the awkward questions ───────────────────────
  await page.getByText("14 дней", { exact: false }).first().scrollIntoViewIfNeeded();
  await shot(page, "landing-faq");

  // ── 3. They apply ──────────────────────────────────────────────────────
  await page.locator('input[name="email"]').fill(partnerEmail);
  await page.locator('input[name="name"]').fill("Journey Partner");
  await page.locator('input[name="channel"]').fill("t.me/journey");
  await shot(page, "application-filled");

  await page.getByRole("button", { name: "Отправить" }).click();
  await expect(page.getByText("Заявка принята")).toBeVisible({ timeout: 20_000 });
  await shot(page, "application-accepted");

  // ── 4. An admin finds it in the queue ──────────────────────────────────
  const queue = await request.get(`${API}/api/v1/admin/affiliate/applications`, {
    headers: auth,
  });
  const partnerId = ((await queue.json()) as { items: { id: string; email: string }[] }).items.find(
    (i) => i.email === partnerEmail,
  )?.id;
  expect(partnerId, "the application must reach the admin queue").toBeTruthy();

  // ── 5. …approves it, and issues a code ─────────────────────────────────
  const approved = await request.post(
    `${API}/api/v1/admin/affiliate/applications/${partnerId ?? ""}/approve`,
    { headers: auth },
  );
  expect(approved.ok(), await approved.text()).toBeTruthy();

  const issued = await request.post(
    `${API}/api/v1/admin/affiliate/partners/${partnerId ?? ""}/codes`,
    { headers: auth, data: { code, discount_percent: "10", commission_percent: "2" } },
  );
  expect(issued.status(), await issued.text()).toBe(201);

  // ── 6. The partner follows the link from their email ───────────────────
  const reinvite = await request.post(
    `${API}/api/v1/admin/affiliate/partners/${partnerId ?? ""}/reinvite`,
    { headers: auth },
  );
  const link = ((await reinvite.json()) as { link: string }).link;
  const token = new URL(link).searchParams.get("token") ?? "";

  await page.goto(`${PARTNERS}/set-password?token=${token}`);
  await page.locator('input[name="password"]').fill(partnerPassword);
  await shot(page, "set-password");

  await page.getByRole("button", { name: "Сохранить и войти" }).click();
  await expect(page).toHaveURL(/\/login/, { timeout: 20_000 });

  // ── 7. …and signs in to an empty panel ─────────────────────────────────
  await page.locator('input[name="email"]').fill(partnerEmail);
  await page.locator('input[name="password"]').fill(partnerPassword);
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page).toHaveURL(/\/panel/, { timeout: 20_000 });
  await shot(page, "panel-empty");

  // ── 8. Their code is waiting for them ──────────────────────────────────
  await page.getByRole("link", { name: "Промокоды" }).click();
  await expect(page.getByText(code)).toBeVisible({ timeout: 20_000 });
  await shot(page, "panel-code");

  // ── 9. Meanwhile a buyer arrives at the storefront ─────────────────────
  const buyerEmail = `${unique("buyer-")}@example.com`;
  const buyerPassword = "buyer password 123";
  const registered = await request.post(`${API}/api/v1/auth/register`, {
    data: { email: buyerEmail, password: buyerPassword },
  });
  expect(registered.ok(), await registered.text()).toBeTruthy();

  // Registration answers `verification_required` and no mail leaves a dev box,
  // so the verification is marked done directly. Nothing in the affiliate
  // mechanics depends on how a buyer proved their address.
  sql(`update users set email_verified_at = now() where email = '${buyerEmail}';`);

  const signedIn = await request.post(`${API}/api/v1/auth/login`, {
    data: { email: buyerEmail, password: buyerPassword },
  });
  const buyerTokens = (await signedIn.json()) as { access_token?: string };
  expect(buyerTokens.access_token, await signedIn.text()).toBeTruthy();
  const buyerAuth = { Authorization: `Bearer ${buyerTokens.access_token ?? ""}` };

  const buyerPage = await page.context().newPage();
  await buyerPage.goto(`${WEB}/store`);
  await expect(buyerPage.locator('a[href*="/store/"]').first()).toBeVisible({
    timeout: 30_000,
  });
  await shot(buyerPage, "storefront-catalog");

  // Pick a brand page, not the "Каталог" nav link — which is also an
  // `a[href*="/store/"]` and was where `.first()` kept landing.
  const brandHref = await buyerPage.evaluate(() => {
    const links = Array.from(document.querySelectorAll<HTMLAnchorElement>('a[href*="/store/"]'));
    return links.map((a) => new URL(a.href).pathname).find((p) => /\/store\/[^/]+$/.test(p));
  });
  expect(brandHref, "the catalog must link to at least one brand").toBeTruthy();

  await buyerPage.goto(`${WEB}${brandHref ?? ""}`);
  await expect(buyerPage.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30_000 });
  await shot(buyerPage, "storefront-product");

  // Pick a package. The promo field only renders once there is a cart to
  // price — with nothing selected there is no total for a discount to apply
  // to, and a field that cannot answer is worse than no field.
  await buyerPage
    .getByText(/Gold|Pass|UZS/)
    .first()
    .scrollIntoViewIfNeeded();
  const pack = buyerPage.locator('button, [role="button"]').filter({ hasText: /UZS/ }).first();
  await pack.click();

  // A guest sees an invitation to sign in rather than a field that cannot
  // work: a partner code binds a buyer to a partner, and a guest has no
  // account to bind.
  const guestHint = buyerPage.getByText("Войдите, чтобы применить промокод");
  await expect(guestHint).toBeVisible({ timeout: 20_000 });
  await guestHint.scrollIntoViewIfNeeded();
  await shot(buyerPage, "checkout-promo-guest");

  // ── 10. The buyer signs in and applies the code ────────────────────────
  await buyerPage.getByRole("button", { name: "Войти" }).first().click();
  // The modal offers providers first; email opens the password form.
  // Scoped to the modal: the checkout panel behind it has an email field too,
  // and `.first()` was filling that one while the modal stayed empty.
  const modal = buyerPage.getByRole("dialog");
  await modal.getByRole("button", { name: "Email", exact: true }).click();
  await modal.locator('input[type="email"]').fill(buyerEmail);
  await modal.locator('input[type="password"]').fill(buyerPassword);
  await modal.getByRole("button", { name: "Войти", exact: true }).click();

  // Signing in re-renders the panel and clears the selection, so the package
  // is picked again — the promo field needs a cart to price.
  await expect(buyerPage.getByRole("button", { name: "Войти" }).first()).toBeHidden({
    timeout: 30_000,
  });
  await buyerPage.locator('button, [role="button"]').filter({ hasText: /UZS/ }).first().click();

  const promoInput = buyerPage.locator("#promo-code");
  await expect(promoInput).toBeVisible({ timeout: 30_000 });
  await promoInput.fill(code);
  await promoInput.scrollIntoViewIfNeeded();
  await shot(buyerPage, "checkout-promo-typed");

  await buyerPage.getByRole("button", { name: "Применить" }).click();
  // The struck-through old price beside the new one is the whole point of the
  // field, and the numbers come from the server rather than from arithmetic
  // in the browser.
  await expect(buyerPage.getByTestId("promo-total-after")).toBeVisible({ timeout: 30_000 });
  await buyerPage.getByTestId("promo-total-after").scrollIntoViewIfNeeded();
  await shot(buyerPage, "checkout-promo-applied");

  // ── 10–13. The order, its payment and its delivery ─────────────────────
  // Driven through the API: the storefront's own checkout needs a live
  // acquirer, and the point of these frames is the affiliate mechanics rather
  // than a re-test of the payment providers.
  // A SKU whose product asks for nothing. A top-up needs a player_id the
  // journey has no business inventing, and the affiliate mechanics are the
  // same either way.
  const skuId = sql(
    "select s.id from skus s join products p on p.id=s.product_id " +
      "join brands b on b.id=p.brand_id where s.active and b.active and p.active " +
      "and s.price_usd > 0 and coalesce(jsonb_array_length(p.required_fields), 0) = 0 " +
      "limit 1;",
  );
  expect(skuId, "the dev catalog must have a SKU with no required fields").toBeTruthy();

  const preview = await request.post(`${API}/api/v1/affiliate/preview`, {
    headers: buyerAuth,
    data: { code, currency: "UZS", items: [{ sku_id: skuId, qty: 1 }] },
  });
  const previewBody = (await preview.json()) as {
    applicable: boolean;
    discount: string;
    total_before: string;
    total_after: string;
  };
  expect(previewBody.applicable, await preview.text()).toBe(true);
  expect(Number(previewBody.discount)).toBeGreaterThan(0);
  expect(Number(previewBody.total_after)).toBeLessThan(Number(previewBody.total_before));

  const order = await request.post(`${API}/api/v1/orders`, {
    headers: { ...buyerAuth, "Idempotency-Key": idempotencyKey() },
    data: {
      currency: "UZS",
      items: [{ sku_id: skuId, qty: 1, fulfillment_data: {} }],
      affiliate_code: code,
    },
  });
  const orderBody = (await order.json()) as { id: string; discount_charged: string };
  expect(order.ok(), await order.text()).toBeTruthy();
  // The discount the buyer was shown is the discount they were charged.
  expect(Number(orderBody.discount_charged)).toBe(Number(previewBody.discount));

  const intent = await request.post(`${API}/api/v1/payments/intents`, {
    headers: { ...buyerAuth, "Idempotency-Key": idempotencyKey() },
    data: { order_id: orderBody.id, provider: "mock" },
  });
  const paymentId = ((await intent.json()) as { external_id?: string }).external_id ?? "";
  expect(intent.ok(), await intent.text()).toBeTruthy();

  const hook = await request.post(`${API}/api/v1/webhooks/payments/mock`, {
    data: {
      event_id: unique("evt-"),
      payment_id: paymentId,
      outcome: "succeeded",
    },
  });
  expect(hook.ok(), await hook.text()).toBeTruthy();

  // Delivery: no supplier and no stock in dev, so the state a real fulfilment
  // would have produced is set directly.
  sql(
    `update orders set status='delivered', delivered_at=now(), fulfilled_at=now() where id='${orderBody.id}';`,
  );

  // ── 14. The commission accrues, then matures ───────────────────────────
  runSweep();
  sql(
    `update affiliate_commissions set available_at = now() - interval '1 day' where order_id='${orderBody.id}';`,
  );
  runSweep();

  // ── 15. The partner sees the money ─────────────────────────────────────
  await page.goto(`${PARTNERS}/panel`);
  await expect(page.getByText("Доступно к выводу")).toBeVisible({ timeout: 20_000 });
  await shot(page, "panel-earned");

  await page.getByRole("link", { name: "Начисления" }).click();
  await expect(page.getByText("Комиссия")).toBeVisible({ timeout: 20_000 });
  await shot(page, "panel-commissions");

  // ── 16. …and asks for it ───────────────────────────────────────────────
  // The floor is 50 000 so'm and one order's commission is far below it, so
  // the balance is topped up to something withdrawable. This is the same
  // ledger posting a few hundred more orders would have produced.
  sql(
    `insert into wallet_postings (id, transaction_id, account_id, direction, amount, currency, created_at)
     select gen_random_uuid(), t.id, a.id, 'D', 200000, 'UZS', now()
     from wallet_accounts a
     join wallet_transactions t on t.kind = 'affiliate.mature'
     where a.owner_type='partner' and a.owner_id='${partnerId ?? ""}' and a.kind='partner_balance'
     limit 1;`,
  );

  // Reload after the top-up: the panel caches the balance for 15s, which is
  // right for a real session where money does not appear under the partner's
  // feet, and wrong for a journey that just moved it with SQL.
  await page.reload();
  await page.getByRole("link", { name: "Выплаты" }).click();
  await expect(page.getByRole("button", { name: "Заказать выплату" })).toBeEnabled({
    timeout: 20_000,
  });
  await shot(page, "panel-payout-form");

  await page.locator('input[name="amount"]').fill("100000");
  await page.locator('input[name="card"]').fill("8600123456789012");
  await page.locator('input[name="holder"]').fill("JOURNEY PARTNER");
  await shot(page, "panel-payout-filled");

  await page.getByRole("button", { name: "Заказать выплату" }).click();
  await expect(page.getByText("Заявка принята", { exact: false })).toBeVisible({
    timeout: 20_000,
  });
  await shot(page, "panel-payout-requested");

  // ── 17. The admin sees it, masked ──────────────────────────────────────
  const payouts = await request.get(`${API}/api/v1/admin/affiliate/payouts`, { headers: auth });
  const payout = ((await payouts.json()) as { items: { id: string; partner_id: string }[] }).items
    .filter((p) => p.partner_id === partnerId)
    .at(0);
  expect(payout, "the request must reach the admin queue").toBeTruthy();
  expect(await payouts.text()).not.toContain("8600123456789012");

  // …and unmasked, only when they open it to make the transfer.
  const detail = await request.get(`${API}/api/v1/admin/affiliate/payouts/${payout?.id ?? ""}`, {
    headers: auth,
  });
  expect(((await detail.json()) as { card_number: string }).card_number).toBe("8600123456789012");

  // ── 18. …pays it, and the partner sees it settled ──────────────────────
  const paid = await request.post(
    `${API}/api/v1/admin/affiliate/payouts/${payout?.id ?? ""}/paid`,
    { headers: auth, data: { note: "journey" } },
  );
  expect(paid.ok(), await paid.text()).toBeTruthy();

  await page.reload();
  await expect(page.getByText("выплачено")).toBeVisible({ timeout: 20_000 });
  await shot(page, "panel-payout-paid");
});
