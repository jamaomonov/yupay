import { describe, expect, test } from "vitest";

import {
  accumulatePage,
  priceFor,
  validateInviteUrl,
  type GiftApp,
  type GiftAppDetail,
} from "./gifts";

// ─── validateInviteUrl ──────────────────────────────────────────────────────
// Table copied from the shapes `GiftPurchasePanel.tsx::isValidInviteUrl`
// accepts/rejects on the web storefront (profiles/\d{17}, /id/vanity,
// s.team/p/path — scheme optional, https-only when given, host compared
// exactly) — this is the same client-side gate, just canonicalizing to a
// `https://` string instead of returning a boolean.
describe("validateInviteUrl", () => {
  const accept: [string, string][] = [
    ["full https profile id64 link", "https://steamcommunity.com/profiles/76561198000000000"],
    ["scheme-optional (bare host+path)", "steamcommunity.com/profiles/76561198000000000"],
    ["surrounding whitespace trimmed", "  https://steamcommunity.com/profiles/76561198000000000  "],
    ["vanity /id/ path", "https://steamcommunity.com/id/my_name-123"],
    ["vanity path at the 2-char floor", "https://steamcommunity.com/id/ab"],
    ["s.team invite link", "https://s.team/p/abcDEF123-_"],
    ["s.team invite with trailing slash", "https://s.team/p/abcDEF123-_/"],
    ["host is case-insensitive", "https://STEAMCOMMUNITY.COM/profiles/76561198000000000"],
  ];

  test.each(accept)("accepts: %s", (_label, input) => {
    expect(validateInviteUrl(input)).not.toBeNull();
  });

  test("canonicalizes a scheme-optional profile link to https://", () => {
    expect(validateInviteUrl("steamcommunity.com/profiles/76561198000000000")).toBe(
      "https://steamcommunity.com/profiles/76561198000000000",
    );
  });

  test("canonicalizes an s.team link, dropping the trailing slash", () => {
    expect(validateInviteUrl("https://s.team/p/abcDEF123-_/")).toBe("https://s.team/p/abcDEF123-_");
  });

  const reject: [string, string][] = [
    ["empty string", ""],
    ["whitespace only", "   "],
    ["wrong host entirely", "https://example.com/not-steam"],
    ["http (not https)", "http://steamcommunity.com/profiles/76561198000000000"],
    ["ftp scheme", "ftp://steamcommunity.com/profiles/76561198000000000"],
    ["id64 too short", "https://steamcommunity.com/profiles/123"],
    ["id64 non-numeric", "https://steamcommunity.com/profiles/7656119800000000A"],
    ["vanity too short (1 char)", "https://steamcommunity.com/id/a"],
    ["vanity too long (33 chars)", `https://steamcommunity.com/id/${"a".repeat(33)}`],
    ["vanity has illegal characters", "https://steamcommunity.com/id/my name"],
    ["unsupported /gid/ path shape", "https://steamcommunity.com/gid/76561198000000000"],
    ["profile with no id segment", "https://steamcommunity.com/profiles"],
    ["s.team missing the path segment", "https://s.team/p"],
    ["s.team wrong first segment", "https://s.team/x/abc"],
    [
      "unrelated steam-looking host",
      "https://steamcommunity.com.evil.example/profiles/76561198000000000",
    ],
  ];

  test.each(reject)("rejects: %s", (_label, input) => {
    expect(validateInviteUrl(input)).toBeNull();
  });
});

// ─── priceFor ───────────────────────────────────────────────────────────────
function makeDetail(overrides: Partial<GiftAppDetail> = {}): GiftAppDetail {
  return {
    app_id: 588650,
    name: "Dead Cells",
    image: null,
    type: "game",
    price_usd: "6.35",
    price_uzs: "75057",
    discount_percent: null,
    packages_count: 1,
    dlc_count: 7,
    description: "A rogue-lite.",
    packages: [
      {
        id: 152266,
        name: "Dead Cells",
        image: null,
        discount_percent: null,
        prices: [
          { zone: "CIS", price_usd: "12.97", price_uzs: "153305" },
          { zone: "RU", price_usd: "6.35", price_uzs: "75057" },
        ],
      },
    ],
    dlc_total: 7,
    zones: ["CIS", "RU", "KZ", "UA"],
    zone_default: "CIS",
    ...overrides,
  };
}

describe("priceFor", () => {
  test("resolves the price for a valid package/zone pair", () => {
    expect(priceFor(makeDetail(), 152266, "RU")).toEqual({
      zone: "RU",
      price_usd: "6.35",
      price_uzs: "75057",
    });
  });

  test("returns null for a zone the package has no price in", () => {
    expect(priceFor(makeDetail(), 152266, "KZ")).toBeNull();
  });

  test("returns null for an unknown package id", () => {
    expect(priceFor(makeDetail(), 999999, "CIS")).toBeNull();
  });

  test("returns null when the detail hasn't loaded yet", () => {
    expect(priceFor(null, 152266, "CIS")).toBeNull();
  });

  test("returns null when nothing is selected yet", () => {
    expect(priceFor(makeDetail(), null, "CIS")).toBeNull();
    expect(priceFor(makeDetail(), 152266, null)).toBeNull();
  });
});

// ─── accumulatePage ─────────────────────────────────────────────────────────
function makeApp(app_id: number, name: string): GiftApp {
  return {
    app_id,
    name,
    image: null,
    type: "game",
    price_usd: null,
    price_uzs: null,
    discount_percent: null,
    packages_count: 0,
    dlc_count: 0,
  };
}

describe("accumulatePage", () => {
  const first = makeApp(1, "A");
  const second = makeApp(2, "B");
  const third = makeApp(3, "C");

  test("a first page (offset 0) replaces whatever was there", () => {
    const prev = { items: [first], total: 1 };
    const next = accumulatePage(prev, { items: [second], total: 5 }, 0);
    expect(next).toEqual({ items: [second], total: 5 });
  });

  test("a later page (offset > 0) appends onto the accumulation", () => {
    const prev = { items: [first, second], total: 5 };
    const next = accumulatePage(prev, { items: [third], total: 5 }, 2);
    expect(next).toEqual({ items: [first, second, third], total: 5 });
  });

  test("does not mutate the previous items array", () => {
    const prevItems = [first];
    const prev = { items: prevItems, total: 5 };
    accumulatePage(prev, { items: [second], total: 5 }, 1);
    expect(prevItems).toEqual([first]);
  });
});
