// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { afterEach, beforeAll, expect, it, vi } from "vitest";

import { OrderStatus } from "./OrderStatus";

import type { OrderOut } from "@/lib/orders-types";
import type { ReactNode } from "react";

/**
 * The "codes are ready" block is gated on more than "delivered + guest": a
 * top-up has no code to hand over. `ArtifactReceipt` renders only real
 * deliverables (code / key / pin / serial) and deliberately excludes a
 * top-up's login, so it returns null for one — meaning the block used to send
 * a Steam buyer off to request an email, follow the link, and land on an empty
 * page. Pinned here because nothing about it is visible in the happy path.
 */

const messages = {
  web: {
    orders: {
      backToOrders: "Back",
      codesReadyTitle: "Codes are ready",
      codesNeedAccess: "Open the order from the email to see them.",
      sendAccessLink: "Email me the link",
      accessLinkSent: "Sent",
      accessLinkFailed: "Failed",
      loading: "…",
      supportCta: "Contact support",
      status: {
        delivered: "Delivered",
        deliveredTopup: "Credited",
      },
      // The rest of the page's copy. Present only so next-intl doesn't log a
      // MISSING_MESSAGE per key — noise that would bury a real failure.
      body: { delivered: "Delivered", deliveredTopup: "Credited to the account" },
      progress: {
        label: "Progress",
        paid: "Paid",
        fulfilling: "Delivering",
        delivered: "Delivered",
        credited: "Credited",
      },
      copyOrderId: "Copy",
      total: "Total",
      paidWith: "Paid with",
      createdAt: "Created",
      paidAt: "Paid",
      deliveredAt: "Delivered",
      itemsTitle: "Items",
      copy: "Copy",
      copied: "Copied",
      receiptTitle: "Your delivery",
      receipt: {
        code: "Code",
      },
    },
    gifts: {
      delivered: {
        title: "Gift sent",
        step1: "Check Steam notifications or email",
        step2: "The sender is a bot account",
        step3: "Accept the gift within 30 days",
        sender: "Sender: YuPay's bot account",
      },
    },
    brandReviews: {
      writeCta: "Write a review",
    },
  },
};

const mockApiFetch = vi.fn<(path: string) => Promise<unknown>>();
vi.mock("@/lib/client", () => ({
  apiFetch: (path: string) => mockApiFetch(path),
}));

vi.mock("@/lib/guest", () => ({
  mintGuestToken: () => Promise.resolve("guest-tok"),
  requestCodeAccess: () => Promise.resolve(undefined),
}));

vi.mock("@/lib/reviews", () => ({
  getMyReviews: () => Promise.resolve({ items: [], total: 0 }),
}));

// No `?access=` in the URL — exactly the state a guest is in when they open the
// order straight after paying, which is when the block appears.
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

// Mutable so individual tests can render as a signed-in buyer (needed to
// reach the deliveries fetch at all — a guest without a valid `?access=`
// link never gets there, see `canLoadCodes` in `OrderStatus.tsx`). Reset to
// `null` (guest) in `afterEach` so the two pre-existing tests, which rely on
// the guest path, are unaffected.
let mockUser: { id: string } | null = null;
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: mockUser }),
}));

vi.mock("@/store/useRealtimeStatus", () => ({
  useRealtimeStatus: (selector: (s: { connected: boolean }) => unknown) =>
    selector({ connected: false }),
}));

// jsdom ships no layout engine, so it has no scrollIntoView — the component
// calls it to bring the codes block into view once it renders.
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(() => {
  vi.clearAllMocks();
  mockUser = null;
});

function wrap(ui: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <NextIntlClientProvider locale="en" messages={messages}>
        {ui}
      </NextIntlClientProvider>
    </QueryClientProvider>,
  );
}

function makeOrder(kind: "top_up" | "voucher"): OrderOut {
  return {
    id: "01a00487-0000-0000-0000-000000000000",
    status: "delivered",
    currency: "UZS",
    total_usd: "1.00",
    total_charged: "13438.00",
    payment_provider: "click",
    fx_snapshot_id: null,
    expires_at: "2026-08-16T00:00:00Z",
    created_at: "2026-08-15T13:26:00Z",
    paid_at: "2026-08-15T13:26:00Z",
    fulfilled_at: null,
    delivered_at: "2026-08-15T13:27:00Z",
    cancelled_at: null,
    items: [
      {
        id: "item-1",
        sku_id: "sku-1",
        qty: 1,
        unit_price_usd: "1.00",
        fulfillment_state: "delivered",
        fulfillment_data: { steam_login: "_jamshid__" },
        display: {
          brand_slug: "steam",
          brand_name: "Steam",
          product_slug: "steam-wallet",
          product_name: "Steam Wallet",
          product_kind: kind,
          sku_code: "steam-wallet-usd",
          denomination: "1,00 $",
          region: "GLOBAL",
          image_url: null,
          variable_amount: true,
        },
      },
    ],
  };
}

it("does not offer a codes link on a delivered top-up — there are none to fetch", async () => {
  mockApiFetch.mockResolvedValue(makeOrder("top_up"));

  wrap(<OrderStatus orderId="01a00487-0000-0000-0000-000000000000" email="buyer@example.com" />);

  // Wait for the order itself so the assertion isn't just racing the fetch.
  // The status hero, not the progress step, which carries the same word.
  expect(await screen.findByRole("heading", { name: "Credited" })).toBeInTheDocument();
  expect(screen.queryByText("Codes are ready")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Email me the link" })).not.toBeInTheDocument();
});

it("still offers it on a delivered voucher, where a real code is waiting", async () => {
  mockApiFetch.mockResolvedValue(makeOrder("voucher"));

  wrap(<OrderStatus orderId="01a00487-0000-0000-0000-000000000000" email="buyer@example.com" />);

  await waitFor(() => {
    expect(screen.getByText("Codes are ready")).toBeInTheDocument();
  });
  expect(screen.getByRole("button", { name: "Email me the link" })).toBeInTheDocument();
});

/**
 * A gift delivery has no code/key to reveal — `ArtifactReceipt` would
 * silently render nothing for it, leaving the buyer with an empty gap. The
 * two tests below cover the branch in `OrderStatus.tsx` that special-cases
 * `artifact.kind === "gift"`: it renders `GiftDeliveryCard` instead of
 * `ArtifactReceipt` for that one delivery, and leaves every other artifact
 * kind on the original `ArtifactReceipt` path, unchanged.
 *
 * Both need the deliveries fetch to actually run, which only happens once
 * `canLoadCodes` is true — a guest without a valid `?access=` link (the
 * shape the two tests above use) never gets there. Rendered as a signed-in
 * buyer instead (`mockUser`), which satisfies `canLoadCodes` unconditionally.
 */
function makeGiftOrder(): OrderOut {
  return {
    id: "01a00487-0000-0000-0000-000000000000",
    status: "delivered",
    currency: "UZS",
    total_usd: "1.10",
    total_charged: "13970.00",
    payment_provider: "click",
    fx_snapshot_id: null,
    expires_at: "2026-08-16T00:00:00Z",
    created_at: "2026-08-15T13:26:00Z",
    paid_at: "2026-08-15T13:26:00Z",
    fulfilled_at: null,
    delivered_at: "2026-08-15T13:27:00Z",
    cancelled_at: null,
    items: [
      {
        id: "item-1",
        sku_id: "sku-1",
        qty: 1,
        unit_price_usd: "1.10",
        fulfillment_state: "delivered",
        fulfillment_data: {},
        display: {
          brand_slug: "steam-gifts",
          brand_name: "Steam Gifts",
          product_slug: "steam-gift",
          product_name: "Steam Gift",
          product_kind: "top_up",
          sku_code: "steam-gift",
          denomination: "Dead Cells",
          region: "CIS",
          image_url: null,
          variable_amount: true,
        },
      },
    ],
  };
}

it('renders the gift instruction card — not ArtifactReceipt — for a "gift" artifact', async () => {
  mockUser = { id: "u1" };
  mockApiFetch.mockImplementation((path: string) => {
    if (path.endsWith("/deliveries")) {
      return Promise.resolve({
        items: [
          {
            id: "d1",
            order_item_id: "item-1",
            channel: "in_app",
            artifact_kind: "topup_receipt",
            artifact: {
              kind: "gift",
              app_name: "Dead Cells",
              package_name: "Standard Edition",
              status: "shipped",
              message: "delivered",
            },
            delivered_at: "2026-08-15T13:27:00Z",
          },
        ],
      });
    }
    return Promise.resolve(makeGiftOrder());
  });

  wrap(<OrderStatus orderId="01a00487-0000-0000-0000-000000000000" />);

  await waitFor(() => {
    expect(screen.getByText("Gift sent")).toBeInTheDocument();
  });
  expect(screen.getByText("Dead Cells — Standard Edition")).toBeInTheDocument();
  expect(screen.getByText("Check Steam notifications or email")).toBeInTheDocument();
  expect(screen.getByText("Sender: YuPay's bot account")).toBeInTheDocument();
  // Never the generic receipt path for a gift delivery.
  expect(screen.queryByText("Your delivery")).not.toBeInTheDocument();
});

it("still renders ArtifactReceipt — not the gift card — for a non-gift artifact", async () => {
  mockUser = { id: "u1" };
  mockApiFetch.mockImplementation((path: string) => {
    if (path.endsWith("/deliveries")) {
      return Promise.resolve({
        items: [
          {
            id: "d2",
            order_item_id: "item-1",
            channel: "in_app",
            artifact_kind: "voucher_code",
            artifact: { kind: "voucher_code", code: "ABC-123-XYZ" },
            delivered_at: "2026-08-15T13:27:00Z",
          },
        ],
      });
    }
    return Promise.resolve(makeOrder("voucher"));
  });

  wrap(<OrderStatus orderId="01a00487-0000-0000-0000-000000000000" />);

  await waitFor(() => {
    expect(screen.getByText("Your delivery")).toBeInTheDocument();
  });
  expect(screen.getByText("ABC-123-XYZ")).toBeInTheDocument();
  // Never the gift instruction card for a non-gift artifact.
  expect(screen.queryByText("Gift sent")).not.toBeInTheDocument();
});
