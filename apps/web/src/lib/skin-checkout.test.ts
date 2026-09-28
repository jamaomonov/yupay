import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clearTokens, setTokens } from "./client";
import {
  buySkin,
  orderKeyFor,
  SignInRequiredError,
  SkinListingGoneError,
  SkinPriceChangedError,
  SkinTradeLinkError,
} from "./skin-checkout";

const LINK = "https://steamcommunity.com/tradeoffer/new/?partner=1039652352&token=LBCWEQ8s";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>();

const params = {
  locale: "ru",
  skuId: "sku-1",
  slug: "ak-47-redline-field-tested",
  listingId: 111,
  tradelink: LINK,
  amountUsd: "30.37",
  provider: "click",
  orderKey: "skin-order-key-000001",
};

beforeEach(() => {
  vi.stubGlobal("window", {
    localStorage: { getItem: () => null, setItem: vi.fn(), removeItem: vi.fn() },
    location: { origin: "https://yupay.uz" },
  });
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  setTokens("jwt");
});

afterEach(() => {
  clearTokens();
  vi.unstubAllGlobals();
});

describe("buySkin", () => {
  it("orders one skin line and starts the payment", async () => {
    fetchMock
      .mockResolvedValueOnce(json(201, { id: "o1" }))
      .mockResolvedValueOnce(json(200, { intent_url: "https://pay.example/x" }));
    const out = await buySkin(params);
    expect(out).toEqual({
      orderId: "o1",
      intentUrl: "https://pay.example/x",
      trackHref: "/orders/o1",
    });
    const [orderUrl, orderInit] = fetchMock.mock.calls[0]!;
    expect(orderUrl).toContain("/api/v1/orders");
    expect(new Headers(orderInit?.headers).get("Idempotency-Key")).toBe(params.orderKey);
    expect(JSON.parse(orderInit?.body as string)).toEqual({
      // apiFetch sends a JSON string
      currency: "UZS",
      items: [
        {
          sku_id: "sku-1",
          qty: 1,
          amount_usd: "30.37",
          fulfillment_data: { slug: params.slug, listing_id: 111, tradelink: LINK },
        },
      ],
    });
    const intentBody = fetchMock.mock.calls[1]![1]?.body as string; // apiFetch sends a JSON string
    const intent = JSON.parse(intentBody) as Record<string, unknown>;
    expect(intent).toMatchObject({ order_id: "o1", provider: "click" });
  });

  it("needs a signed-in buyer", async () => {
    clearTokens();
    await expect(buySkin(params)).rejects.toBeInstanceOf(SignInRequiredError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("names a moved price", async () => {
    fetchMock.mockResolvedValueOnce(json(422, { extra: { expected_amount_usd: "31.10" } }));
    await expect(buySkin(params)).rejects.toEqual(new SkinPriceChangedError("31.10"));
  });

  it("offers the next listing when the chosen one is gone", async () => {
    const next = { listing_id: 222, price_usd: "30.90" };
    fetchMock.mockResolvedValueOnce(
      json(422, { extra: { reason: "listing_gone", next_offer: next } }),
    );
    const err = await buySkin(params).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(SkinListingGoneError);
    expect((err as SkinListingGoneError).nextOffer).toEqual(next);
  });

  it("names a trade link that belongs to another account", async () => {
    fetchMock.mockResolvedValueOnce(json(422, { extra: { reason: "tradelink_other_account" } }));
    const err = await buySkin(params).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(SkinTradeLinkError);
    expect((err as SkinTradeLinkError).reason).toBe("tradelink_other_account");
  });
});

describe("orderKeyFor", () => {
  const mint = () => "fresh";
  const k1 = { listingId: 1, tradelink: "A", key: "k1" };

  it("keeps the key for a retry of the same offer to the same link", () => {
    expect(orderKeyFor(k1, 1, "A", mint)).toEqual(k1);
  });

  it("mints a new key for another offer or another trade link", () => {
    expect(orderKeyFor(k1, 2, "A", mint).key).toBe("fresh");
    // A replayed order would still deliver to the old link.
    expect(orderKeyFor(k1, 1, "B", mint)).toEqual({ listingId: 1, tradelink: "B", key: "fresh" });
    expect(orderKeyFor(null, 1, "A", mint).key).toBe("fresh");
  });
});
