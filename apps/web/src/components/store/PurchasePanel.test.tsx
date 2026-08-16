// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { PurchasePanel } from "./PurchasePanel";

import type { ProductDetail } from "@/lib/catalog";

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
