import { describe, expect, it } from "vitest";

import {
  checkAmount,
  formatUsdt,
  groupUsdt,
  isPreset,
  sanitizeAmount,
  explorerTxLink,
  isUsdtNetwork,
  networkLabel,
  shortHash,
  toCents,
  trustWalletLink,
  usdtErrorKey,
  usdtPhase,
  usdtPollDeadline,
  USDT_NETWORKS,
} from "./usdt";

import type { UsdtDeposit } from "./types";

const base: Omit<UsdtDeposit, "status"> = {
  number: "U1",
  amount: "100.01",
  network: "trc20",
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

describe("groupUsdt", () => {
  it("groups thousands with a narrow no-break space and keeps the point", () => {
    expect(groupUsdt("1000.00")).toBe("1\u202F000.00");
    expect(groupUsdt("1234567.89")).toBe("1\u202F234\u202F567.89");
    expect(groupUsdt("100.01")).toBe("100.01");
    expect(groupUsdt("5")).toBe("5");
    expect(groupUsdt("12345")).toBe("12\u202F345");
  });

  it("leaves anything that is not a plain decimal as sent", () => {
    expect(groupUsdt("1e3")).toBe("1e3");
    expect(groupUsdt("")).toBe("");
    expect(groupUsdt("1,000.00")).toBe("1,000.00");
  });
});

describe("isPreset", () => {
  it("matches the amount box against a whole preset, exactly", () => {
    expect(isPreset("1000", 1000)).toBe(true);
    expect(isPreset("1000.00", 1000)).toBe(true);
    expect(isPreset("1000.01", 1000)).toBe(false);
    expect(isPreset("", 100)).toBe(false);
    expect(isPreset("100.", 100)).toBe(true);
  });
});

describe("networks", () => {
  it("names each chain with its standard and knows only these three", () => {
    expect(networkLabel("trc20")).toBe("TRON (TRC20)");
    expect(networkLabel("bep20")).toBe("BNB Chain (BEP20)");
    expect(networkLabel("erc20")).toBe("Ethereum (ERC20)");
    expect(isUsdtNetwork("bep20")).toBe(true);
    expect(isUsdtNetwork("TRC20")).toBe(false);
    expect(isUsdtNetwork("toString")).toBe(false);
  });

  it("points each chain at its logo", () => {
    expect(USDT_NETWORKS.trc20.logo).toBe("/crypto/tron.png");
    expect(USDT_NETWORKS.bep20.logo).toBe("/crypto/bnb.png");
    expect(USDT_NETWORKS.erc20.logo).toBe("/crypto/eth.png");
  });
});

describe("links and hashes", () => {
  it("builds the Trust Wallet send link with the chain's USDT, address and amount", () => {
    const send = "https://link.trustwallet.com/send?asset=";
    expect(trustWalletLink("trc20", "TXyz", "100.01")).toBe(
      `${send}c195_tTR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t&address=TXyz&amount=100.01`,
    );
    expect(trustWalletLink("bep20", "0xAb", "5")).toBe(
      `${send}c20000714_t0x55d398326f99059fF775485246999027B3197955&address=0xAb&amount=5`,
    );
    expect(trustWalletLink("erc20", "0xAb", "5")).toBe(
      `${send}c60_t0xdAC17F958D2ee523a2206206994597C13D831ec7&address=0xAb&amount=5`,
    );
  });

  it("links a transaction on the chain's explorer and shortens its hash", () => {
    const tx = "a".repeat(30) + "b".repeat(34);
    expect(explorerTxLink("trc20", tx)).toBe(`https://tronscan.org/#/transaction/${tx}`);
    expect(explorerTxLink("bep20", `0x${tx}`)).toBe(`https://bscscan.com/tx/0x${tx}`);
    expect(explorerTxLink("erc20", `0x${tx}`)).toBe(`https://etherscan.io/tx/0x${tx}`);
    expect(shortHash(tx)).toBe("aaaaaa…bbbbbb");
    expect(shortHash("short")).toBe("short");
  });
});

describe("usdtErrorKey", () => {
  it("maps the codes it has a message for", () => {
    expect(usdtErrorKey("usdt_amount_precision")).toBe("errPrecision");
    expect(usdtErrorKey("usdt_amount_busy")).toBe("errAmountBusy");
    expect(usdtErrorKey("usdt_idempotency_mismatch")).toBe("errRetry");
    expect(usdtErrorKey("usdt_network_disabled")).toBe("errNetworkOff");
    expect(usdtErrorKey("other")).toBeNull();
  });
});
