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
