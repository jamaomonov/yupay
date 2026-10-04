import { describe, expect, it } from "vitest";

import { phase, secondsLeft, usdPreview } from "./p2p";

describe("secondsLeft", () => {
  it("counts down and stops at zero", () => {
    const exp = "2026-10-04T05:00:00Z";
    expect(secondsLeft(exp, Date.parse("2026-10-04T04:57:30Z"))).toBe(150);
    expect(secondsLeft(exp, Date.parse("2026-10-04T05:01:00Z"))).toBe(0);
  });
});

describe("usdPreview", () => {
  it("rounds down to cents like the server", () => {
    expect(usdPreview(50_000, "12300")).toBe("4.06");
    expect(usdPreview(50_000, null)).toBeNull();
    expect(usdPreview(0, "12300")).toBeNull();
  });

  it("handles fractional and high-precision rates exactly", () => {
    expect(usdPreview(50_000, "12345.67")).toBe("4.05");
    // Just under 10.00: a float rate that rounds to 12300 would say "10.00".
    expect(usdPreview(123_000, "12300")).toBe("10.00");
    expect(usdPreview(123_000, "12300.000001")).toBe("9.99");
  });

  it("rejects bad input without Infinity or NaN", () => {
    expect(usdPreview(50_000, "abc")).toBeNull();
    expect(usdPreview(50_000, "0")).toBeNull();
    expect(usdPreview(50_000, "1e3")).toBeNull();
    expect(usdPreview(50_000, "-5")).toBeNull();
    expect(usdPreview(Number.POSITIVE_INFINITY, "12300")).toBeNull();
    expect(usdPreview(Number.NaN, "12300")).toBeNull();
    expect(usdPreview(1e21, "12300")).toBeNull();
  });
});

describe("phase", () => {
  it("maps statuses to screens", () => {
    expect(phase(null)).toBe("amount");
    const base = {
      number: "T1",
      amount_uzs: 1,
      amount_usd: "0",
      fx_rate: "1",
      created_at: "",
      expires_at: "",
      closed_at: null,
      card: null,
    };
    expect(phase({ ...base, status: "pending" })).toBe("details");
    expect(phase({ ...base, status: "paid" })).toBe("paid");
    expect(phase({ ...base, status: "expired" })).toBe("expired");
    expect(phase({ ...base, status: "cancelled" })).toBe("cancelled");
  });
});

describe("errorKey and formatClock", () => {
  it("maps codes and formats the clock", async () => {
    const { errorKey, formatClock } = await import("./p2p");
    expect(errorKey("p2p_no_card")).toBe("errNoCard");
    expect(errorKey("p2p_amount_busy")).toBe("errBusy");
    expect(errorKey("fx_unavailable")).toBe("errRate");
    expect(errorKey("x")).toBeNull();
    expect(formatClock(305)).toBe("5:05");
  });
});
