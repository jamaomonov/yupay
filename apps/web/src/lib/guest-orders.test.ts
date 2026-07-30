import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  listGuestOrders,
  removeGuestOrders,
  saveGuestOrder,
  type GuestOrder,
} from "./guest-orders";

/** Minimal localStorage backed by a Map — mirrors client.test.ts's fake. */
function fakeStorage() {
  const store = new Map<string, string>();
  return {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  };
}

function order(orderId: string, createdAt: string): GuestOrder {
  return {
    orderId,
    email: "buyer@example.com",
    brandSlug: "pubg",
    brandName: "PUBG Mobile",
    createdAt,
  };
}

beforeEach(() => {
  vi.stubGlobal("window", { localStorage: fakeStorage() });
});

describe("guest-orders", () => {
  it("returns an empty list when nothing is stored", () => {
    expect(listGuestOrders()).toEqual([]);
  });

  it("saveGuestOrder appends and listGuestOrders returns newest-first", () => {
    saveGuestOrder(order("o1", "2026-07-01T00:00:00.000Z"));
    saveGuestOrder(order("o2", "2026-07-02T00:00:00.000Z"));

    expect(listGuestOrders().map((o) => o.orderId)).toEqual(["o2", "o1"]);
  });

  it("saveGuestOrder dedupes by orderId, moving the updated entry to the front", () => {
    saveGuestOrder(order("o1", "2026-07-01T00:00:00.000Z"));
    saveGuestOrder(order("o2", "2026-07-02T00:00:00.000Z"));
    saveGuestOrder(order("o1", "2026-07-03T00:00:00.000Z"));

    const list = listGuestOrders();
    expect(list.map((o) => o.orderId)).toEqual(["o1", "o2"]);
    expect(list[0]?.createdAt).toBe("2026-07-03T00:00:00.000Z");
  });

  it("caps storage at 50 entries, keeping the newest", () => {
    for (let i = 0; i < 55; i++) {
      saveGuestOrder(order(`o${String(i)}`, `2026-07-01T00:00:${String(i).padStart(2, "0")}.000Z`));
    }

    const list = listGuestOrders();
    expect(list).toHaveLength(50);
    // Newest (o54) first; oldest 5 (o0..o4) evicted.
    expect(list[0]?.orderId).toBe("o54");
    expect(list.map((o) => o.orderId)).not.toContain("o0");
    expect(list.map((o) => o.orderId)).not.toContain("o4");
  });

  it("removeGuestOrders drops the given ids and keeps the rest", () => {
    saveGuestOrder(order("o1", "2026-07-01T00:00:00.000Z"));
    saveGuestOrder(order("o2", "2026-07-02T00:00:00.000Z"));
    saveGuestOrder(order("o3", "2026-07-03T00:00:00.000Z"));

    removeGuestOrders(["o1", "o3"]);

    expect(listGuestOrders().map((o) => o.orderId)).toEqual(["o2"]);
  });

  it("listGuestOrders returns [] and never throws on corrupt JSON", () => {
    window.localStorage.setItem("yupay.web.guest_orders", "{not json");

    expect(listGuestOrders()).toEqual([]);
  });

  it("listGuestOrders returns [] when the stored value isn't an array", () => {
    window.localStorage.setItem("yupay.web.guest_orders", JSON.stringify({ not: "an array" }));

    expect(listGuestOrders()).toEqual([]);
  });

  it("saveGuestOrder and removeGuestOrders are no-ops when window is undefined", () => {
    vi.stubGlobal("window", undefined);

    expect(() => {
      saveGuestOrder(order("o1", "2026-07-01T00:00:00.000Z"));
      removeGuestOrders(["o1"]);
    }).not.toThrow();
    expect(listGuestOrders()).toEqual([]);
  });
});
