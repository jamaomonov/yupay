// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { PurchasePanel } from "./PurchasePanel";

import type { ProductDetail } from "@/lib/catalog";

import { formatUzs } from "@/lib/seo";

vi.mock("next-intl", () => ({
  useTranslations: () => (k: string) => k,
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: null }),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function mockProvidersResponse(
  providers: { slug: string; status: "active" | "maintenance" }[],
): void {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ json: () => Promise.resolve({ providers }) }));
}

function makeProduct(): ProductDetail {
  return {
    id: "prod-1",
    slug: "steam",
    brand_slug: "steam",
    category_slug: "wallets",
    name: "Steam Wallet",
    short_description: null,
    image_url: null,
    kind: "top_up",
    starting_price_usd: "10.00",
    starting_display_price: null,
    brand: {
      id: "brand-1",
      slug: "steam",
      category_slug: "wallets",
      name: "Steam",
      short_description: null,
      logo_url: null,
      hero_image_url: null,
      accent_color: null,
      maintenance: false,
    },
    description: null,
    required_fields: [],
    skus: [
      {
        id: "sku-1",
        sku_code: "STEAM-10",
        denomination: "$10",
        region: null,
        image_url: null,
        price_usd: "10.00",
        display_price: { amount: "1250000", currency: "UZS", source: "fx" },
      },
    ],
  };
}

/** A Telegram-Stars-shaped product: one fixed pack plus a free amount typed in
 *  Stars (64.705882 per dollar, $0.7727–$772.7 → 50–50 000 Stars). */
function makeUnitProduct(): ProductDetail {
  const base = makeProduct();
  return {
    ...base,
    skus: [
      { ...base.skus[0]!, id: "sku-pack", sku_code: "STARS-50", denomination: "50 Stars" },
      {
        ...base.skus[0]!,
        id: "sku-var",
        sku_code: "STARS-VAR",
        denomination: "Stars",
        variable_amount: true,
        amount_unit: "Stars",
        units_per_usd: "64.705882",
        min_amount_usd: "0.7727",
        max_amount_usd: "772.7",
        display_price: { amount: "12500", currency: "UZS", source: "fx" },
      },
    ],
  };
}

/**
 * A genuine unit SKU (`min_qty`/`max_qty` set, `variable_amount` false) —
 * what Telegram Stars becomes once it stops using the legacy
 * `variable_amount` + `units_per_usd` path that `makeUnitProduct` above
 * still exercises. One SKU, no separate pack SKUs: the package tiles are
 * built client-side from `visibleStarPackages`, not from the catalog.
 */
function makeStarsUnitProduct(): ProductDetail {
  const base = makeProduct();
  return {
    ...base,
    skus: [
      {
        ...base.skus[0]!,
        id: "sku-unit",
        sku_code: "STARS-UNIT",
        denomination: "Stars",
        image_url: "/stars.webp",
        variable_amount: false,
        amount_unit: "Stars",
        min_qty: 50,
        max_qty: 2500,
        display_price: { amount: "250", currency: "UZS", source: "fx" },
      },
    ],
  };
}

it("renders Stars package tiles from the unit SKU's rate, not separate pack SKUs", async () => {
  mockProvidersResponse([{ slug: "click", status: "active" }]);
  render(<PurchasePanel products={[makeStarsUnitProduct()]} locale="ru" />);
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Click" })).not.toBeDisabled();
  });

  // The full working list, bounded to [50, 2500] — every entry is visible.
  // Anchored: "150 Stars" and "1 500 Stars" both contain "50 Stars" as a
  // substring, which an unanchored regex would also match.
  const fifty = screen.getByRole("button", { name: /^50 Stars\b/ });
  const seventyFive = screen.getByRole("button", { name: /^75 Stars\b/ });
  expect(fifty).toBeInTheDocument();
  expect(seventyFive).toBeInTheDocument();
  // packagePrice(50, 250) = 12 500 — N times the per-star display_price, no
  // volume-discount band and no server round-trip.
  expect(fifty.textContent).toContain(formatUzs("ru", 12_500));
  // Same SKU art on every tile — there is one unit SKU, not one image per pack.
  expect(fifty.querySelector("img")).toHaveAttribute("src", expect.stringContaining("stars.webp"));
  expect(seventyFive.querySelector("img")).toHaveAttribute(
    "src",
    expect.stringContaining("stars.webp"),
  );

  // The amount field is also here, denominated in Stars, not a pack SKU.
  const field = screen.getByLabelText("amountUnitLabel");
  expect(field).toHaveAttribute("inputMode", "numeric");
  expect(field).toHaveAttribute("placeholder", "50");
});

it("falls back to the product image when the unit SKU has none", async () => {
  mockProvidersResponse([{ slug: "click", status: "active" }]);
  const product = makeStarsUnitProduct();
  product.image_url = "/product.webp";
  product.skus[0] = { ...product.skus[0]!, image_url: null };
  render(<PurchasePanel products={[product]} locale="ru" />);
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Click" })).not.toBeDisabled();
  });
  expect(screen.getByRole("button", { name: /^50 Stars\b/ }).querySelector("img")).toHaveAttribute(
    "src",
    expect.stringContaining("product.webp"),
  );
});

interface CapturedOrderItem {
  sku_id: string;
  qty: number;
  amount_usd?: string;
}

it("submits a tapped pack as { sku_id, qty } with no amount_usd", async () => {
  // A box rather than a reassigned `let`: the assignment happens inside the
  // mock's callback, and boxing it sidesteps TS narrowing the outer binding
  // via control flow it can't see into.
  const captured: { orderItems: CapturedOrderItem[] | null } = { orderItems: null };
  vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    const url = input instanceof Request ? input.url : String(input);
    if (url.includes("/payments/providers")) {
      return Promise.resolve(
        new Response(JSON.stringify({ providers: [{ slug: "click", status: "active" }] }), {
          status: 200,
        }),
      );
    }
    if (url.includes("/auth/guest")) {
      return Promise.resolve(
        new Response(JSON.stringify({ access_token: "guest-token" }), { status: 200 }),
      );
    }
    if (url.includes("/api/v1/orders") && init?.method === "POST") {
      const body = JSON.parse(init.body as string) as { items: CapturedOrderItem[] };
      captured.orderItems = body.items;
      return Promise.resolve(new Response(JSON.stringify({ id: "order-1" }), { status: 200 }));
    }
    if (url.includes("/payments/intents")) {
      return Promise.resolve(new Response(JSON.stringify({ intent_url: null }), { status: 200 }));
    }
    return Promise.resolve(new Response("{}", { status: 200 }));
  });

  render(<PurchasePanel products={[makeStarsUnitProduct()]} locale="ru" />);
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Click" })).not.toBeDisabled();
  });

  fireEvent.click(screen.getByRole("button", { name: /^50 Stars\b/ }));
  fireEvent.change(screen.getByPlaceholderText("emailPlaceholder"), {
    target: { value: "buyer@example.com" },
  });

  await waitFor(() => {
    expect(screen.getByRole("button", { name: /^pay ·/i })).not.toBeDisabled();
  });
  fireEvent.click(screen.getByRole("button", { name: /^pay ·/i }));
  fireEvent.click(await screen.findByRole("button", { name: "confirmCta" }));

  await waitFor(() => {
    expect(captured.orderItems).not.toBeNull();
  });
  expect(captured.orderItems).toEqual([expect.objectContaining({ sku_id: "sku-unit", qty: 50 })]);
  expect(captured.orderItems?.[0]).not.toHaveProperty("amount_usd");
});

it("puts the free-amount field above the packages and says nothing about rate or fees", async () => {
  // The old card asked for dollars while the customer was buying Stars, hid the
  // field under the grid, and wrapped it in a rate / "комиссия 0%" / limit
  // panel plus a slider and its own duplicate $100/$250/$500 presets.
  mockProvidersResponse([{ slug: "click", status: "active" }]);
  render(<PurchasePanel products={[makeUnitProduct()]} locale="ru" />);
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Click" })).not.toBeDisabled();
  });

  const field = screen.getByLabelText("amountUnitLabel");
  const pack = screen.getByRole("button", { name: /50 Stars/ });
  // DOCUMENT_POSITION_FOLLOWING === the pack comes after the field.
  expect(field.compareDocumentPosition(pack) & 4).toBeTruthy();

  // Denominated in the unit, never in dollars: the label carries "Stars" and
  // the placeholder is the smallest count, not "например, 10".
  expect(field).toHaveAttribute("placeholder", "50");
  expect(field).toHaveAttribute("inputMode", "numeric");
  expect(screen.getByText("amountRange")).toBeInTheDocument();

  for (const gone of ["rateLabel", "feeLabel", "limitLabel", "feeNote", "amountSubtitle"]) {
    expect(screen.queryByText(gone)).not.toBeInTheDocument();
  }
  expect(screen.queryByRole("slider")).not.toBeInTheDocument();
});

it("makes the typed amount and a package mutually exclusive", async () => {
  mockProvidersResponse([{ slug: "click", status: "active" }]);
  render(<PurchasePanel products={[makeUnitProduct()]} locale="ru" />);
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Click" })).not.toBeDisabled();
  });

  const field = screen.getByLabelText("amountUnitLabel");
  const pack = screen.getByRole("button", { name: /50 Stars/ });

  // Focus precedes input in a real browser — that is what selects the SKU.
  fireEvent.focus(field);
  fireEvent.change(field, { target: { value: "100" } });
  expect(field).toHaveValue("100");
  expect(pack).toHaveAttribute("aria-pressed", "false");

  fireEvent.click(pack);
  expect(pack).toHaveAttribute("aria-pressed", "true");
  expect(field).toHaveValue("");
});

it("keeps the dollar wording for a SKU with no unit (Steam)", async () => {
  mockProvidersResponse([{ slug: "click", status: "active" }]);
  const base = makeProduct();
  const steam: ProductDetail = {
    ...base,
    skus: [
      {
        ...base.skus[0]!,
        variable_amount: true,
        amount_unit: null,
        units_per_usd: null,
        min_amount_usd: "1",
        max_amount_usd: "300",
      },
    ],
  };
  render(<PurchasePanel products={[steam]} locale="ru" />);
  // Let the provider-status fetch settle so it doesn't resolve outside act().
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Click" })).not.toBeDisabled();
  });

  const field = screen.getByLabelText("amountOwn");
  expect(field).toHaveAttribute("placeholder", "amountPlaceholder");
  expect(field).toHaveAttribute("inputMode", "decimal");
  // No packages to choose from, so the heading stays the amount one.
  expect(screen.getByRole("heading", { name: "amountTitle" })).toBeInTheDocument();
});

// `METHODS` (module-level in PurchasePanel.tsx) is [click, payme, uzum]; the
// component defaults `methodId` to the first entry (click) before it knows
// anything about live provider status.

it("reselects the first active method when the hardcoded default (click) is under maintenance", async () => {
  mockProvidersResponse([
    { slug: "click", status: "maintenance" },
    { slug: "payme", status: "active" },
    // uzum omitted entirely -> admin-disabled, must not render at all.
  ]);

  render(<PurchasePanel products={[makeProduct()]} locale="ru" />);

  await waitFor(() => {
    const click = screen.getByRole("button", { name: "Click" });
    const payme = screen.getByRole("button", { name: "Payme" });
    expect(click).toBeDisabled();
    expect(payme).not.toBeDisabled();
    // Auto-reselected away from the disabled default onto the only active method.
    expect(payme).toHaveAttribute("aria-pressed", "true");
    expect(click).toHaveAttribute("aria-pressed", "false");
  });

  expect(screen.queryByRole("button", { name: "Uzum" })).not.toBeInTheDocument();
});

it("shows the maintenance status as an overlay chip, outside the tile's flow", async () => {
  mockProvidersResponse([
    { slug: "click", status: "maintenance" },
    { slug: "payme", status: "active" },
  ]);

  render(<PurchasePanel products={[makeProduct()]} locale="ru" />);

  const click = await screen.findByRole("button", { name: "Click" });
  const chip = await screen.findByText("paymentMaintenanceShort");
  // Absolutely positioned: a status that participated in the flow made this
  // tile taller than its siblings, which is the bug this guards.
  expect(chip.className).toContain("absolute");
  // The chip describes the tile; it must not become part of its name, or
  // every "is Click still Click" query in this suite drifts with the copy.
  expect(click).toHaveAttribute("aria-describedby", chip.id);
  expect(screen.getByRole("button", { name: "Payme" })).not.toHaveAttribute("aria-describedby");
});

it("disables Pay when no payment provider is active", async () => {
  mockProvidersResponse([
    { slug: "click", status: "maintenance" },
    { slug: "payme", status: "maintenance" },
    // uzum omitted -> hidden too, so literally nothing is selectable.
  ]);

  render(<PurchasePanel products={[makeProduct()]} locale="ru" />);

  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Click" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Payme" })).toBeDisabled();
  });
  expect(screen.queryByRole("button", { name: "Uzum" })).not.toBeInTheDocument();

  // Fill in everything else Pay would otherwise need, so the assertion below
  // isolates the "no active provider" gate specifically.
  fireEvent.change(screen.getByPlaceholderText("emailPlaceholder"), {
    target: { value: "buyer@example.com" },
  });

  // The desktop summary card's Pay button carries the actual `disabled`
  // attribute gated on `canPay` (its name is "pay · <price>" — the mobile
  // sticky bar's button has no such attribute; it branches in its onClick
  // handler instead, which is unrelated to this fix).
  expect(screen.getByRole("button", { name: /^pay ·/i })).toBeDisabled();
});

it("does not block checkout on an attestation checkbox for a gift card with no account fields", async () => {
  // `hasVerifiableField = fields.some(...)` is `false` on an EMPTY array too,
  // which used to read as "needs attestation" and rendered a checkbox
  // referencing an account field the buyer never saw — for a gift card
  // (kind: "voucher", no required_fields) there's nothing to attest to.
  mockProvidersResponse([{ slug: "click", status: "active" }]);
  const product: ProductDetail = { ...makeProduct(), kind: "voucher" };

  render(<PurchasePanel products={[product]} locale="ru" />);

  fireEvent.change(screen.getByPlaceholderText("emailPlaceholder"), {
    target: { value: "buyer@example.com" },
  });

  await waitFor(() => {
    expect(screen.getByRole("button", { name: /^pay ·/i })).not.toBeDisabled();
  });
  fireEvent.click(screen.getByRole("button", { name: /^pay ·/i }));

  expect(await screen.findByRole("dialog")).toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "confirmCta" })).not.toBeDisabled();
  // The voucher-flavoured warning, not the top-up "goes to the account shown" one.
  expect(screen.getByText("confirmWarningVoucher")).toBeInTheDocument();
});

it("hides a plain field's help text behind a button instead of always showing it", async () => {
  // A field with no `check` (e.g. the miHoYo titles, or a plain "Сервер"
  // select) used to dump help_text as an always-visible paragraph under the
  // control. It should only appear once the "Где найти?" pill is clicked.
  mockProvidersResponse([{ slug: "click", status: "active" }]);
  const helpCopy = "Сервер виден на экране входа рядом с именем аккаунта.";
  const product: ProductDetail = {
    ...makeProduct(),
    required_fields: [
      {
        key: "server",
        label: { ru: "Сервер" },
        type: "select",
        required: true,
        help_text: { ru: helpCopy },
        options: [{ value: "europe", label: { ru: "Europe" } }],
      },
    ],
  };

  render(<PurchasePanel products={[product]} locale="ru" />);

  expect(screen.queryByText(helpCopy)).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "whereToFindGeneric" }));

  expect(await screen.findByText(helpCopy)).toBeInTheDocument();
});

it("disables the check button and explains why until the paired server field is filled in", async () => {
  // check.server_field names a sibling field (MLBB's "server") — G2B needs
  // both together, so an id-only lookup against an empty server used to
  // silently misfire instead of being blocked with an explanation.
  mockProvidersResponse([{ slug: "click", status: "active" }]);
  const product: ProductDetail = {
    ...makeProduct(),
    required_fields: [
      {
        key: "player_id",
        label: { ru: "ID игрока" },
        type: "text",
        required: true,
        pattern: "^[0-9]{5,20}$",
        check: { provider: "g2b", server_field: "server" },
      },
      {
        key: "server",
        label: { ru: "ID сервера" },
        type: "text",
        required: true,
      },
    ],
  };

  render(<PurchasePanel products={[product]} locale="ru" />);

  // Let the async provider-status fetch settle before touching state, so its
  // resolution isn't left dangling outside act() by the rest of this test.
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Click" })).not.toBeDisabled();
  });

  fireEvent.change(screen.getByPlaceholderText("playerIdPlaceholder"), {
    target: { value: "51234567" },
  });

  // `aria-disabled`, not `disabled`: the button has to keep receiving clicks
  // so pressing it can say what is missing (a real `disabled` swallows them).
  const checkBtn = screen.getByRole("button", { name: "check" });
  expect(checkBtn).toHaveAttribute("aria-disabled", "true");
  expect(screen.getByText("checkNeedsServer")).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText("ID сервера *"), { target: { value: "19450" } });

  expect(checkBtn).toHaveAttribute("aria-disabled", "false");
  expect(screen.queryByText("checkNeedsServer")).not.toBeInTheDocument();
});

/** The two MLBB-shaped fields: a checked player id plus its sibling server. */
const MLBB_FIELDS: ProductDetail["required_fields"] = [
  {
    key: "player_id",
    label: { ru: "ID игрока" },
    type: "text",
    required: true,
    pattern: "^[0-9]{5,20}$",
    check: { provider: "g2b", server_field: "server" },
  },
  { key: "server", label: { ru: "ID сервера" }, type: "text", required: true },
];

it("keeps the check blocked when only the server id is filled in", async () => {
  // Reported from prod as an asymmetry: id-without-server correctly refused,
  // server-without-id happily ran. Both halves are needed either way round.
  mockProvidersResponse([{ slug: "click", status: "active" }]);
  render(
    <PurchasePanel products={[{ ...makeProduct(), required_fields: MLBB_FIELDS }]} locale="ru" />,
  );
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Click" })).not.toBeDisabled();
  });

  fireEvent.change(screen.getByLabelText("ID сервера *"), { target: { value: "6618" } });

  const checkBtn = screen.getByRole("button", { name: "check" });
  expect(checkBtn).toHaveAttribute("aria-disabled", "true");
  // Silent until pressed — nagging for an id the customer has not reached yet
  // would be noise.
  expect(screen.queryByText("checkNeedsId")).not.toBeInTheDocument();

  fireEvent.click(checkBtn);

  expect(screen.getByText("checkNeedsId")).toBeInTheDocument();
});

it("will not check a region-split brand until a package is picked", async () => {
  // Two products = one per account region (ADR-0048). The form renders from
  // products[0] so it is usable immediately, but running the lookup against
  // that arbitrary product verifies a Russian id against the global game and
  // calls it not-found — the FAQ then sends the buyer to the wrong region.
  mockProvidersResponse([{ slug: "click", status: "active" }]);
  // Two SKUs each: a lone SKU auto-selects (see `skuId`'s initialiser), and
  // the real products carry 13 and 10 denominations, so nothing is picked for
  // the customer.
  const base = makeProduct();
  const global: ProductDetail = {
    ...base,
    required_fields: MLBB_FIELDS,
    skus: [
      { ...base.skus[0]!, id: "sku-1", sku_code: "MLBB-86" },
      { ...base.skus[0]!, id: "sku-1b", sku_code: "MLBB-172" },
    ],
  };
  const ru: ProductDetail = {
    ...global,
    id: "prod-2",
    slug: "mlbb-diamonds-ru",
    skus: [
      { ...base.skus[0]!, id: "sku-2", sku_code: "MLBB-RU-86" },
      { ...base.skus[0]!, id: "sku-2b", sku_code: "MLBB-RU-172" },
    ],
  };
  render(<PurchasePanel products={[global, ru]} locale="ru" />);
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Click" })).not.toBeDisabled();
  });

  fireEvent.change(screen.getByPlaceholderText("playerIdPlaceholder"), {
    target: { value: "1313232551" },
  });
  fireEvent.change(screen.getByLabelText("ID сервера *"), { target: { value: "6618" } });

  // Both ids present and still blocked: which product to ask is the open
  // question, and no amount of typing answers it.
  const checkBtn = screen.getByRole("button", { name: "check" });
  expect(checkBtn).toHaveAttribute("aria-disabled", "true");
  expect(screen.getByText("checkNeedsSku")).toBeInTheDocument();
});

it("checks straight away on a single-product brand", async () => {
  // Nothing to disambiguate, so requiring a package here would be a pointless
  // extra step.
  mockProvidersResponse([{ slug: "click", status: "active" }]);
  render(
    <PurchasePanel products={[{ ...makeProduct(), required_fields: MLBB_FIELDS }]} locale="ru" />,
  );
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Click" })).not.toBeDisabled();
  });

  fireEvent.change(screen.getByPlaceholderText("playerIdPlaceholder"), {
    target: { value: "1313232551" },
  });
  fireEvent.change(screen.getByLabelText("ID сервера *"), { target: { value: "6618" } });

  expect(screen.getByRole("button", { name: "check" })).toHaveAttribute("aria-disabled", "false");
  expect(screen.queryByText("checkNeedsSku")).not.toBeInTheDocument();
});

it("keeps Pay disabled until the checkable field passes verification", async () => {
  // A filled-in id used to be enough to reach the acquirer — a typo then
  // landed the top-up on a stranger's account with no way back. Pay must
  // stay blocked until "Проверить" actually confirms the id.
  mockProvidersResponse([{ slug: "click", status: "active" }]);
  render(
    <PurchasePanel products={[{ ...makeProduct(), required_fields: MLBB_FIELDS }]} locale="ru" />,
  );
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Click" })).not.toBeDisabled();
  });

  fireEvent.change(screen.getByPlaceholderText("playerIdPlaceholder"), {
    target: { value: "1313232551" },
  });
  fireEvent.change(screen.getByLabelText("ID сервера *"), { target: { value: "6618" } });
  fireEvent.change(screen.getByPlaceholderText("emailPlaceholder"), {
    target: { value: "buyer@example.com" },
  });

  expect(screen.getByRole("button", { name: /^pay ·/i })).toBeDisabled();
  expect(screen.getAllByText("payHintVerify").length).toBeGreaterThan(0);
});

it("enables Pay once the checkable field's check comes back valid", async () => {
  mockProvidersResponse([{ slug: "click", status: "active" }]);
  vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
    const url = input instanceof Request ? input.url : String(input);
    if (url.includes("check-player")) {
      return Promise.resolve(
        new Response(JSON.stringify({ status: "valid", name: "blood moon" }), { status: 200 }),
      );
    }
    return Promise.resolve(
      new Response(JSON.stringify({ providers: [{ slug: "click", status: "active" }] }), {
        status: 200,
      }),
    );
  });
  render(
    <PurchasePanel products={[{ ...makeProduct(), required_fields: MLBB_FIELDS }]} locale="ru" />,
  );
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Click" })).not.toBeDisabled();
  });

  fireEvent.change(screen.getByPlaceholderText("playerIdPlaceholder"), {
    target: { value: "1313232551" },
  });
  fireEvent.change(screen.getByLabelText("ID сервера *"), { target: { value: "6618" } });
  fireEvent.change(screen.getByPlaceholderText("emailPlaceholder"), {
    target: { value: "buyer@example.com" },
  });
  fireEvent.click(screen.getByRole("button", { name: "check" }));

  expect(await screen.findByText("blood moon")).toBeInTheDocument();
  // The pill's own render and the parent's `checkResults` update (an effect,
  // mirrored up a tick after the pill commits) are two separate renders —
  // `findByText` above only guarantees the first one happened.
  await waitFor(() => {
    expect(screen.getByRole("button", { name: /^pay ·/i })).not.toBeDisabled();
  });
});

it("drops a confirmed nickname when the package switches to another product", async () => {
  // Found on prod with Playwright: verify a Russian id, then pick a global
  // package, and the green pill stayed — a nickname confirmed against the
  // other region, shown as reassurance for the one about to be paid for.
  mockProvidersResponse([{ slug: "click", status: "active" }]);
  vi.spyOn(globalThis, "fetch").mockImplementation((input: RequestInfo | URL) => {
    // `RequestInfo` covers `Request`, which stringifies to "[object Object]".
    const url = input instanceof Request ? input.url : String(input);
    if (url.includes("check-player")) {
      return Promise.resolve(
        new Response(JSON.stringify({ status: "valid", name: "blood moon" }), { status: 200 }),
      );
    }
    return Promise.resolve(
      new Response(JSON.stringify({ providers: [{ slug: "click", status: "active" }] }), {
        status: 200,
      }),
    );
  });

  const base = makeProduct();
  // Distinct denominations so each package button is uniquely addressable.
  const ruSkus = [
    { ...base.skus[0]!, id: "sku-ru-1", sku_code: "MLBB-RU-86", denomination: "RU 86" },
    { ...base.skus[0]!, id: "sku-ru-2", sku_code: "MLBB-RU-172", denomination: "RU 172" },
  ];
  const globalSkus = [
    { ...base.skus[0]!, id: "sku-gl-1", sku_code: "MLBB-86", denomination: "GL 86" },
    { ...base.skus[0]!, id: "sku-gl-2", sku_code: "MLBB-172", denomination: "GL 172" },
  ];
  const globalProduct: ProductDetail = {
    ...base,
    required_fields: MLBB_FIELDS,
    skus: globalSkus,
  };
  const ruProduct: ProductDetail = {
    ...globalProduct,
    id: "prod-ru",
    slug: "mlbb-diamonds-ru",
    skus: ruSkus,
  };
  render(<PurchasePanel products={[globalProduct, ruProduct]} locale="ru" />);
  await waitFor(() => {
    expect(screen.getByRole("button", { name: "Click" })).not.toBeDisabled();
  });

  // Pick the RU package, fill both ids, verify.
  fireEvent.click(screen.getByRole("button", { name: /RU 86/ }));
  fireEvent.change(screen.getByPlaceholderText("playerIdPlaceholder"), {
    target: { value: "1313232551" },
  });
  fireEvent.change(screen.getByLabelText("ID сервера *"), { target: { value: "6618" } });
  fireEvent.click(screen.getByRole("button", { name: "check" }));

  expect(await screen.findByText("blood moon")).toBeInTheDocument();

  // Switch to a package belonging to the other product.
  fireEvent.click(screen.getByRole("button", { name: /GL 86/ }));

  expect(screen.queryByText("blood moon")).not.toBeInTheDocument();
});
