import { describe, expect, test } from "vitest";

import { walletTopUpOffered } from "./WalletPayOption";

/**
 * Whether `WalletPayOption` offers its "top up your balance" link — shipped
 * inline with no test at all (2026-09-04 review round 1), pulled out pure
 * here and tested directly under this app's node-env convention (no
 * jsdom/RTL, so the component itself can't be rendered).
 */
describe("walletTopUpOffered", () => {
  test("offered when the balance is genuinely short", () => {
    expect(
      walletTopUpOffered({
        maintenance: false,
        unknownTotal: false,
        loading: false,
        enough: false,
      }),
    ).toBe(true);
  });

  test("not offered once the balance covers the total", () => {
    expect(
      walletTopUpOffered({ maintenance: false, unknownTotal: false, loading: false, enough: true }),
    ).toBe(false);
  });

  test("not offered under maintenance — nothing to top up towards", () => {
    expect(
      walletTopUpOffered({ maintenance: true, unknownTotal: false, loading: false, enough: false }),
    ).toBe(false);
  });

  test("not offered while the total is unknown (FX unavailable) — no shortfall to quote", () => {
    expect(
      walletTopUpOffered({ maintenance: false, unknownTotal: true, loading: false, enough: false }),
    ).toBe(false);
  });

  test("not offered while the balance is still loading — nothing to compare yet", () => {
    expect(
      walletTopUpOffered({ maintenance: false, unknownTotal: false, loading: true, enough: false }),
    ).toBe(false);
  });

  test("maintenance wins even when every other input would otherwise offer it", () => {
    expect(
      walletTopUpOffered({ maintenance: true, unknownTotal: true, loading: true, enough: false }),
    ).toBe(false);
  });
});
