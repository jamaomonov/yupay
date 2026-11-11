import { describe, expect, it } from "vitest";

import {
  checkAmount,
  formatUsdt,
  sanitizeAmount,
  shortHash,
  toCents,
  tronscanLink,
  trustWalletLink,
  usdtErrorKey,
  usdtPhase,
  usdtPollDeadline,
} from "./usdt";

import type { UsdtDeposit } from "./types";

const base: Omit<UsdtDeposit, "status"> = {
  number: "U1",
  amount: "100.01",
  network: "TRC20",
  address: null,
  created_at: "2026-11-11T10:00:00Z",
  expires_at: "2026-11-11T11:00:00Z",
  closed_at: null,
  tx_id: null,
};

describe("usdtPhase", () => {
  it("maps statuses to screens", () => {
    expect(usdtPhase(null)).toBe("amount");
    expect(usdtPhase({ ...base, status: "pending" })).toBe("details");
    expect(usdtPhase({ ...base, status: "paid" })).toBe("paid");
    expect(usdtPhase({ ...base, status: "expired" })).toBe("expired");
    expect(usdtPhase({ ...base, status: "cancelled" })).toBe("cancelled");
  });
});

describe("usdtPollDeadline", () => {
  it("keeps polling ten minutes past expiry, for a late-read on-time transfer", () => {
    const end = Date.parse("2026-11-11T11:10:00Z");
    expect(usdtPollDeadline({ ...base, status: "pending" })).toBe(end);
    expect(usdtPollDeadline({ ...base, status: "expired" })).toBe(end);
  });

  it("stops for paid, cancelled and nothing", () => {
    expect(usdtPollDeadline({ ...base, status: "paid" })).toBeNull();
    expect(usdtPollDeadline({ ...base, status: "cancelled" })).toBeNull();
    expect(usdtPollDeadline(null)).toBeNull();
  });
});

describe("sanitizeAmount", () => {
  it("keeps digits and one point, two decimals at most", () => {
    expect(sanitizeAmount("150,505")).toBe("150.50");
    expect(sanitizeAmount("1 000 USDT")).toBe("1000");
    expect(sanitizeAmount("1.2.3")).toBe("1.23");
    expect(sanitizeAmount(".5")).toBe("0.5");
    expect(sanitizeAmount("123456789")).toBe("1234567");
    expect(sanitizeAmount("")).toBe("");
  });
});

describe("toCents and checkAmount", () => {
  it("parses decimal strings exactly", () => {
    expect(toCents("100")).toBe(10_000n);
    expect(toCents("100.5")).toBe(10_050n);
    expect(toCents("100.")).toBe(10_000n);
    expect(toCents("1.234")).toBeNull();
    expect(toCents("abc")).toBeNull();
  });

  it("checks against the bounds, either of which may be missing", () => {
    expect(checkAmount("", "10.00", "5000.00")).toBe("empty");
    expect(checkAmount("0", "10.00", "5000.00")).toBe("empty");
    expect(checkAmount("9.99", "10.00", "5000.00")).toBe("low");
    expect(checkAmount("10", "10.00", "5000.00")).toBe("ok");
    expect(checkAmount("5000.01", "10.00", "5000.00")).toBe("high");
    expect(checkAmount("999999", null, null)).toBe("ok");
  });
});

describe("formatUsdt", () => {
  it("groups the whole part and keeps two decimals, no float", () => {
    expect(formatUsdt("1234.5", "en")).toBe("1,234.50");
    expect(formatUsdt("100.01", "en")).toBe("100.01");
    expect(formatUsdt("100", "ru")).toBe("100");
    expect(formatUsdt("100.5", "ru")).toBe("100,50");
    expect(formatUsdt("1e3", "en")).toBe("1e3");
  });
});

describe("links and hashes", () => {
  it("builds the Trust Wallet send link with address and amount", () => {
    expect(trustWalletLink("TXyz", "100.01")).toBe(
      "https://link.trustwallet.com/send?asset=c195_tTR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t&address=TXyz&amount=100.01",
    );
  });

  it("links a transaction on Tronscan and shortens its hash", () => {
    const tx = "a".repeat(30) + "b".repeat(34);
    expect(tronscanLink(tx)).toBe(`https://tronscan.org/#/transaction/${tx}`);
    expect(shortHash(tx)).toBe("aaaaaa…bbbbbb");
    expect(shortHash("short")).toBe("short");
  });
});

describe("usdtErrorKey", () => {
  it("maps the codes it has a message for", () => {
    expect(usdtErrorKey("usdt_amount_precision")).toBe("errPrecision");
    expect(usdtErrorKey("usdt_amount_busy")).toBe("errAmountBusy");
    expect(usdtErrorKey("usdt_idempotency_mismatch")).toBe("errRetry");
    expect(usdtErrorKey("other")).toBeNull();
  });
});
