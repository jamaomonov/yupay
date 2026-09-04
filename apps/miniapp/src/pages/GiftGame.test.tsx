import { describe, expect, test } from "vitest";

import {
  countryAfterPackageChange,
  isOrderNotAwaitingPaymentConflict,
  nextOrderKeyState,
  nextSelectedMethodId,
  orderFingerprint,
  reconcileSelection,
  splitCountries,
  walletPayState,
  walletSubmitReady,
} from "./GiftGame";

import type { GiftAppDetail, GiftPackage, GiftRegion } from "@/lib/gifts";
import type { ProviderAvailability } from "@/lib/orders";

import { ApiError } from "@/lib/api";

function makePackage(id: number, prices: { zone: string; price_usd: string }[]): GiftPackage {
  return {
    id,
    name: `Edition ${String(id)}`,
    image: null,
    discount_percent: null,
    prices: prices.map((p) => ({ zone: p.zone, price_usd: p.price_usd, price_uzs: null })),
  };
}

/** One country per zone, country code === zone label for readability — the
 *  logic under test only cares about the country <-> zone mapping shape,
 *  not real ISO codes (those are `./regions.test.ts`'s job). */
function makeRegions(pairs: [country: string, zone: string][]): GiftRegion[] {
  return pairs.map(([country, zone]) => ({ country, zone, price_usd: "0", price_uzs: null }));
}

function makeDetail(
  packages: GiftPackage[],
  regions: GiftRegion[],
  regionDefault: string,
): GiftAppDetail {
  return {
    app_id: 1,
    name: "Game",
    image: null,
    type: "game",
    price_usd: null,
    price_uzs: null,
    discount_percent: null,
    packages_count: packages.length,
    dlc_count: 0,
    description: null,
    packages,
    dlc_total: 0,
    regions,
    region_default: regionDefault,
  };
}

// Mirrors `GiftPurchasePanel.tsx::selectPackage` on the web storefront: a
// package/edition switch keeps the current country when its zone is still
// priced, otherwise falls back to the app's default country, then to
// whatever country covers the package's first price, and leaves the country
// untouched only when the package has no prices at all (nothing sensible to
// fall back to) — or the fallback zone maps to no known country.
describe("countryAfterPackageChange", () => {
  const regions = makeRegions([
    ["UZ", "CIS"],
    ["RU", "RU"],
    ["KZ", "KZ"],
    ["UA", "UA"],
  ]);

  test("keeps the current country when the new package still prices its zone", () => {
    const pkg = makePackage(1, [
      { zone: "CIS", price_usd: "1" },
      { zone: "RU", price_usd: "2" },
    ]);
    expect(countryAfterPackageChange(pkg, "RU", "UZ", regions)).toBe("RU");
  });

  test("falls back to the app's default country when the current one isn't priced", () => {
    const pkg = makePackage(1, [
      { zone: "CIS", price_usd: "1" },
      { zone: "KZ", price_usd: "3" },
    ]);
    expect(countryAfterPackageChange(pkg, "RU", "UZ", regions)).toBe("UZ");
  });

  test("falls back to a country covering the package's first price when neither current nor default is priced", () => {
    const pkg = makePackage(1, [{ zone: "UA", price_usd: "4" }]);
    expect(countryAfterPackageChange(pkg, "RU", "UZ", regions)).toBe("UA");
  });

  test("leaves the country unchanged when the package has no prices at all", () => {
    const pkg = makePackage(1, []);
    expect(countryAfterPackageChange(pkg, "RU", "UZ", regions)).toBe("RU");
  });

  test("leaves the country unchanged when the fallback zone maps to no known country", () => {
    const pkg = makePackage(1, [{ zone: "MENA", price_usd: "9" }]);
    expect(countryAfterPackageChange(pkg, "RU", "UZ", regions)).toBe("RU");
  });
});

describe("splitCountries", () => {
  test("splits at the visible count", () => {
    expect(splitCountries(["UZ", "RU", "KZ", "UA", "TJ"], 4)).toEqual({
      visible: ["UZ", "RU", "KZ", "UA"],
      overflow: ["TJ"],
    });
  });

  test("empty overflow when everything fits", () => {
    expect(splitCountries(["UZ", "RU"], 4)).toEqual({ visible: ["UZ", "RU"], overflow: [] });
  });

  test("handles an empty country list", () => {
    expect(splitCountries([], 4)).toEqual({ visible: [], overflow: [] });
  });
});

// Guards the price-drift reload path in `GiftGame.tsx::handleBuy`: on a 422
// price-drift refresh, `load(true)` must reapply what the buyer had picked
// instead of resetting to `packages[0]`/`region_default` like a fresh load.
describe("reconcileSelection", () => {
  test("keeps the previously selected package and country when both still exist", () => {
    const regions = makeRegions([
      ["UZ", "CIS"],
      ["RU", "RU"],
    ]);
    const detail = makeDetail(
      [
        makePackage(1, [{ zone: "CIS", price_usd: "1" }]),
        makePackage(2, [
          { zone: "CIS", price_usd: "2" },
          { zone: "RU", price_usd: "3" },
        ]),
      ],
      regions,
      "UZ",
    );
    expect(reconcileSelection(detail, 2, "RU")).toEqual({ packageId: 2, country: "RU" });
  });

  test("falls back to the first package when the previous one was dropped", () => {
    const regions = makeRegions([["UZ", "CIS"]]);
    const detail = makeDetail([makePackage(1, [{ zone: "CIS", price_usd: "1" }])], regions, "UZ");
    expect(reconcileSelection(detail, 99, "UZ")).toEqual({ packageId: 1, country: "UZ" });
  });

  test("re-resolves the country via countryAfterPackageChange when the kept package no longer prices it", () => {
    const regions = makeRegions([
      ["UZ", "CIS"],
      ["RU", "RU"],
    ]);
    const detail = makeDetail([makePackage(1, [{ zone: "CIS", price_usd: "1" }])], regions, "UZ");
    expect(reconcileSelection(detail, 1, "RU")).toEqual({ packageId: 1, country: "UZ" });
  });

  test("falls back to the app's default country when there was no previous country", () => {
    const regions = makeRegions([
      ["UZ", "CIS"],
      ["RU", "RU"],
    ]);
    const detail = makeDetail(
      [
        makePackage(1, [
          { zone: "CIS", price_usd: "1" },
          { zone: "RU", price_usd: "2" },
        ]),
      ],
      regions,
      "UZ",
    );
    expect(reconcileSelection(detail, 1, null)).toEqual({ packageId: 1, country: "UZ" });
  });

  test("returns a null package and keeps the previous country when the detail has no packages", () => {
    const regions = makeRegions([["UZ", "CIS"]]);
    const detail = makeDetail([], regions, "UZ");
    expect(reconcileSelection(detail, 1, "RU")).toEqual({ packageId: null, country: "RU" });
  });

  test("never throws when the detail predates the country picker entirely (version-skewed API)", () => {
    // Same version-skew case as `gifts.test.ts::priceFor` — a detail with
    // `regions`/`region_default` absent outright must degrade, not throw;
    // `GiftGame`'s own `countries.length === 0` guard is what actually
    // keeps this off screen in practice, but the pure function must still
    // be safe to call directly.
    const detail = makeDetail([makePackage(1, [{ zone: "CIS", price_usd: "1" }])], [], "UZ");
    const { regions: _regions, region_default: _regionDefault, ...withoutRegions } = detail;
    expect(() => reconcileSelection(withoutRegions, 1, null)).not.toThrow();
  });
});

// Wallet ("pay from balance") affordability decision — mirrors `TopUp.tsx`'s
// inline `walletEnough`/`walletShortfall`/`disabled` math (see
// `WalletPayOption.tsx`), extracted here as a pure function so it's
// testable under this app's node-env convention (no RTL, no rendering).
// `total` is the selected region's `price_uzs` — `null` only when FX is
// unavailable, which must degrade to a non-selectable "unknown total"
// state rather than comparing against a guessed number.
describe("walletPayState", () => {
  test("is optimistically enough while the balance is still loading", () => {
    expect(
      walletPayState({ balance: null, total: 100_000, loading: true, visibility: "active" }),
    ).toEqual({ enough: true, disabled: false, shortfall: 0, unknownTotal: false });
  });

  test("is enough when the balance covers the total exactly", () => {
    expect(
      walletPayState({ balance: 100_000, total: 100_000, loading: false, visibility: "active" }),
    ).toEqual({ enough: true, disabled: false, shortfall: 0, unknownTotal: false });
  });

  test("is enough when the balance exceeds the total", () => {
    expect(
      walletPayState({ balance: 150_000, total: 100_000, loading: false, visibility: "active" }),
    ).toEqual({ enough: true, disabled: false, shortfall: 0, unknownTotal: false });
  });

  test("is short and disabled when the balance doesn't cover the total", () => {
    expect(
      walletPayState({ balance: 40_000, total: 100_000, loading: false, visibility: "active" }),
    ).toEqual({ enough: false, disabled: true, shortfall: 60_000, unknownTotal: false });
  });

  test("maintenance disables the tile even when the balance is enough", () => {
    expect(
      walletPayState({
        balance: 150_000,
        total: 100_000,
        loading: false,
        visibility: "maintenance",
      }),
    ).toEqual({ enough: true, disabled: true, shortfall: 0, unknownTotal: false });
  });

  test("a null total (FX-unavailable price_uzs) is a disabled unknown state, never a guessed shortfall", () => {
    expect(
      walletPayState({ balance: 150_000, total: null, loading: false, visibility: "active" }),
    ).toEqual({ enough: false, disabled: true, shortfall: 0, unknownTotal: true });
  });

  test("a null total overrides the loading optimism — there's nothing to be optimistic about", () => {
    expect(
      walletPayState({ balance: null, total: null, loading: true, visibility: "active" }),
    ).toEqual({ enough: false, disabled: true, shortfall: 0, unknownTotal: true });
  });
});

// Whether Buy may actually be submitted for the currently selected method —
// the CRITICAL/IMPORTANT parity fixes (2026-09-04 review): the wallet tile
// itself shows an optimistic "enough" while the balance is still loading
// (`walletPayState` above), but this is the honest gate the Buy button
// itself must consult — a live-payment path, so it's asserted directly.
describe("walletSubmitReady", () => {
  test("is always ready for a non-wallet method, regardless of balance/total — the acquirer path is untouched", () => {
    expect(walletSubmitReady({ methodId: "click", balance: null, total: null })).toBe(true);
    expect(walletSubmitReady({ methodId: "click", balance: 0, total: 100_000 })).toBe(true);
    expect(walletSubmitReady({ methodId: "payme", balance: 40_000, total: 100_000 })).toBe(true);
  });

  test("wallet is NOT ready while the balance is still loading (balance === null)", () => {
    expect(walletSubmitReady({ methodId: "wallet", balance: null, total: 100_000 })).toBe(false);
  });

  test("wallet is NOT ready when the total is unknown (FX unavailable)", () => {
    expect(walletSubmitReady({ methodId: "wallet", balance: 150_000, total: null })).toBe(false);
  });

  test("wallet is NOT ready when the balance falls short of the total", () => {
    expect(walletSubmitReady({ methodId: "wallet", balance: 40_000, total: 100_000 })).toBe(false);
  });

  test("wallet IS ready when the balance covers the total", () => {
    expect(walletSubmitReady({ methodId: "wallet", balance: 150_000, total: 100_000 })).toBe(true);
  });

  test("wallet IS ready when the balance covers the total exactly", () => {
    expect(walletSubmitReady({ methodId: "wallet", balance: 100_000, total: 100_000 })).toBe(true);
  });
});

// The reselect effect's own decision, pulled out pure — the CRITICAL parity
// fix: a chosen wallet must never be silently reassigned to a card just
// because its own live status isn't "active". Mirrors
// `GiftPurchasePanel.tsx`'s identical guard on the web storefront.
describe("nextSelectedMethodId", () => {
  const methods = [{ id: "click" }, { id: "payme" }];
  const providerByMethod = { click: "click_miniapp", payme: "payme", wallet: "wallet" };

  test("leaves the selection alone while provider status hasn't loaded yet", () => {
    expect(
      nextSelectedMethodId({
        current: "click",
        statusBySlug: null,
        providerByMethod,
        methods,
      }),
    ).toBe("click");
  });

  test("keeps a chosen wallet selected even when the wallet itself is hidden (admin-disabled)", () => {
    const statusBySlug = new Map<string, ProviderAvailability>([["click_miniapp", "active"]]);
    expect(
      nextSelectedMethodId({ current: "wallet", statusBySlug, providerByMethod, methods }),
    ).toBe("wallet");
  });

  test("keeps a chosen wallet selected even when it's under maintenance", () => {
    const statusBySlug = new Map<string, ProviderAvailability>([
      ["click_miniapp", "active"],
      ["wallet", "maintenance"],
    ]);
    expect(
      nextSelectedMethodId({ current: "wallet", statusBySlug, providerByMethod, methods }),
    ).toBe("wallet");
  });

  test("keeps a chosen wallet selected when it's active too (the trivial case)", () => {
    const statusBySlug = new Map<string, ProviderAvailability>([["wallet", "active"]]);
    expect(
      nextSelectedMethodId({ current: "wallet", statusBySlug, providerByMethod, methods }),
    ).toBe("wallet");
  });

  test("leaves an empty selection empty", () => {
    const statusBySlug = new Map<string, ProviderAvailability>([["click_miniapp", "active"]]);
    expect(nextSelectedMethodId({ current: "", statusBySlug, providerByMethod, methods })).toBe("");
  });

  test("keeps the current acquirer when it's still active", () => {
    const statusBySlug = new Map<string, ProviderAvailability>([
      ["click_miniapp", "active"],
      ["payme", "active"],
    ]);
    expect(
      nextSelectedMethodId({ current: "click", statusBySlug, providerByMethod, methods }),
    ).toBe("click");
  });

  test("falls back to the first active acquirer when the current one is no longer available", () => {
    const statusBySlug = new Map<string, ProviderAvailability>([
      ["click_miniapp", "maintenance"],
      ["payme", "active"],
    ]);
    expect(
      nextSelectedMethodId({ current: "click", statusBySlug, providerByMethod, methods }),
    ).toBe("payme");
  });

  test("deselects entirely when nothing is active", () => {
    const statusBySlug = new Map<string, ProviderAvailability>([
      ["click_miniapp", "maintenance"],
      ["payme", "maintenance"],
    ]);
    expect(
      nextSelectedMethodId({ current: "click", statusBySlug, providerByMethod, methods }),
    ).toBe("");
  });
});

// ---------- sticky order idempotency key ----------
//
// A buyer who retries after a failed payment (typically "insufficient
// wallet balance", re-checked under a row lock server-side) must resume the
// SAME order instead of creating a second one. `create_order` already
// replays by `Idempotency-Key` (`_existing_idempotent_order` in
// `orders/service.py`) — the gap was purely that `handleBuy` minted a fresh
// key on every click. `orderFingerprint` + `nextOrderKeyState` are the
// correctness-by-construction fix, mirroring
// `apps/web/src/lib/gift-checkout.ts` exactly (this page has no delivery
// email field, so the fingerprint has no `email` term). Exported pure and
// tested directly — this app's Vitest suite runs under `environment:
// "node"`, no jsdom/React Testing Library, so `handleBuy` itself can't be
// exercised by rendering.

function baseFingerprintInput() {
  return {
    skuId: "sku-1",
    amountUsd: "1.10",
    fulfillmentData: {
      app_id: 588650,
      package_id: 1,
      region: "UZ",
      invite_url: "https://steamcommunity.com/profiles/76561198000000000",
    },
  };
}

describe("orderFingerprint", () => {
  test("is stable for the exact same order contents", () => {
    expect(orderFingerprint(baseFingerprintInput())).toBe(orderFingerprint(baseFingerprintInput()));
  });

  test("changes when sku_id changes", () => {
    const a = orderFingerprint(baseFingerprintInput());
    const b = orderFingerprint({ ...baseFingerprintInput(), skuId: "sku-2" });
    expect(a).not.toBe(b);
  });

  test("changes when amount_usd changes", () => {
    const a = orderFingerprint(baseFingerprintInput());
    const b = orderFingerprint({ ...baseFingerprintInput(), amountUsd: "1.30" });
    expect(a).not.toBe(b);
  });

  test("changes when fulfillment_data.app_id changes", () => {
    const base = baseFingerprintInput();
    const a = orderFingerprint(base);
    const b = orderFingerprint({
      ...base,
      fulfillmentData: { ...base.fulfillmentData, app_id: 12345 },
    });
    expect(a).not.toBe(b);
  });

  test("changes when fulfillment_data.package_id changes (edition switch)", () => {
    const base = baseFingerprintInput();
    const a = orderFingerprint(base);
    const b = orderFingerprint({
      ...base,
      fulfillmentData: { ...base.fulfillmentData, package_id: 2 },
    });
    expect(a).not.toBe(b);
  });

  test("changes when fulfillment_data.region changes", () => {
    const base = baseFingerprintInput();
    const a = orderFingerprint(base);
    const b = orderFingerprint({
      ...base,
      fulfillmentData: { ...base.fulfillmentData, region: "RU" },
    });
    expect(a).not.toBe(b);
  });

  test("changes when fulfillment_data.invite_url changes (recipient switch)", () => {
    const base = baseFingerprintInput();
    const a = orderFingerprint(base);
    const b = orderFingerprint({
      ...base,
      fulfillmentData: {
        ...base.fulfillmentData,
        invite_url: "https://steamcommunity.com/profiles/76561198000000001",
      },
    });
    expect(a).not.toBe(b);
  });

  test("has no field for the payment method — the input type cannot even carry one", () => {
    // Two fingerprints built for what would be two different payment
    // methods are identical, because `OrderFingerprintInput` has no
    // `provider`/`methodId` term at all: switching card <-> wallet is the
    // same order, never a new one.
    const a = orderFingerprint(baseFingerprintInput());
    const b = orderFingerprint(baseFingerprintInput());
    expect(a).toBe(b);
  });
});

// `nextOrderKeyState` is the "should I mint a new key?" decision `handleBuy`
// applies on every buy click, pulled out pure. `mintKey` is injected so
// tests can assert exactly when it does (mint) or doesn't (reuse) get
// called, instead of asserting against real random UUIDs.
describe("nextOrderKeyState", () => {
  test("mints a key on the first attempt (no prior state)", () => {
    const mint = () => "key-1";
    expect(nextOrderKeyState(null, "fp-a", mint)).toEqual({ fingerprint: "fp-a", key: "key-1" });
  });

  test("same inputs twice reuse the same key — a retry with unchanged fingerprint never re-mints", () => {
    const first = nextOrderKeyState(null, "fp-a", () => "key-1");
    let minted = false;
    const second = nextOrderKeyState(first, "fp-a", () => {
      minted = true;
      return "key-2";
    });
    expect(second).toBe(first);
    expect(second.key).toBe("key-1");
    expect(minted).toBe(false);
  });

  test("a changed fingerprint (region/edition/invite/email) mints a different key", () => {
    const first = nextOrderKeyState(null, "fp-a", () => "key-1");
    const second = nextOrderKeyState(first, "fp-b", () => "key-2");
    expect(second.key).not.toBe(first.key);
    expect(second.fingerprint).toBe("fp-b");
  });

  test("a changed payment method keeps the same key — same fingerprint, since the method never enters it", () => {
    // `orderFingerprint` never takes a payment method, so the fingerprint
    // computed for "click" and for "wallet" is the same string; feeding
    // that same fingerprint through twice must reuse the key exactly like
    // the "same inputs twice" case above.
    const fingerprintForClick = orderFingerprint(baseFingerprintInput());
    const fingerprintForWallet = orderFingerprint(baseFingerprintInput());
    const first = nextOrderKeyState(null, fingerprintForClick, () => "key-1");
    const second = nextOrderKeyState(first, fingerprintForWallet, () => "key-2");
    expect(second).toBe(first);
  });

  test("after a success clears the state to null, the next purchase mints a fresh key even with identical inputs", () => {
    const first = nextOrderKeyState(null, "fp-a", () => "key-1");
    // `handleBuy` sets `orderKeyRef.current = null` on success.
    const afterSuccess = null;
    const second = nextOrderKeyState(afterSuccess, "fp-a", () => "key-2");
    expect(second.key).not.toBe(first.key);
  });
});

describe("isOrderNotAwaitingPaymentConflict", () => {
  test("matches the exact 409 shape create_intent raises for an order that walked past pending_payment", () => {
    const err = new ApiError(409, "Conflict", {
      detail: "order is not awaiting payment",
      extra: { status: "expired" },
    });
    expect(isOrderNotAwaitingPaymentConflict(err)).toBe(true);
  });

  test("does not match a 409 from a different conflict shape on the same endpoint", () => {
    // Every sibling conflict from create_intent uses a different `extra`
    // key (e.g. `extra.provider` / `extra.current_provider`) — matched
    // structurally on `extra.status` being a string, never on message text.
    const err = new ApiError(409, "Conflict", {
      detail: "insufficient wallet balance: have 1000 need 5000",
      extra: { current_provider: "wallet" },
    });
    expect(isOrderNotAwaitingPaymentConflict(err)).toBe(false);
  });

  test("does not match a 409 with no extra object at all", () => {
    const err = new ApiError(409, "Conflict", { detail: "insufficient wallet balance" });
    expect(isOrderNotAwaitingPaymentConflict(err)).toBe(false);
  });

  test("does not match a non-409 ApiError", () => {
    const err = new ApiError(422, "Unprocessable Entity", {
      detail: "gift price changed",
      extra: { status: "expired" },
    });
    expect(isOrderNotAwaitingPaymentConflict(err)).toBe(false);
  });

  test("does not match a plain Error or non-ApiError value", () => {
    expect(isOrderNotAwaitingPaymentConflict(new Error("network blip"))).toBe(false);
    expect(isOrderNotAwaitingPaymentConflict("nope")).toBe(false);
    expect(isOrderNotAwaitingPaymentConflict(null)).toBe(false);
  });
});
