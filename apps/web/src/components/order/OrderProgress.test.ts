import { describe, expect, it } from "vitest";

import { isTrackedStatus, progressFor } from "./OrderProgress";

describe("progressFor", () => {
  it("awaits payment on a fresh order", () => {
    expect(progressFor("pending_payment")).toEqual(["active", "upcoming", "upcoming"]);
  });

  it("moves to fulfilment once paid", () => {
    expect(progressFor("paid")).toEqual(["done", "active", "upcoming"]);
    expect(progressFor("fulfilling")).toEqual(["done", "active", "upcoming"]);
  });

  it("treats `fulfilled` as delivery-in-progress, not delivered", () => {
    // The supplier finished but the customer hasn't got the artifact yet —
    // showing all three ticks here would promise something that hasn't happened.
    expect(progressFor("fulfilled")).toEqual(["done", "done", "active"]);
  });

  it("completes every step once delivered", () => {
    expect(progressFor("delivered")).toEqual(["done", "done", "done"]);
  });

  it("shows nothing in progress for an unknown status", () => {
    expect(progressFor("weird")).toEqual(["upcoming", "upcoming", "upcoming"]);
  });
});

describe("isTrackedStatus", () => {
  it("covers the happy path", () => {
    for (const s of ["pending_payment", "paid", "fulfilling", "fulfilled", "delivered"]) {
      expect(isTrackedStatus(s)).toBe(true);
    }
  });

  it("excludes terminal-bad states — a timeline would imply progress", () => {
    for (const s of ["failed", "cancelled", "expired", "refunded", "partially_refunded"]) {
      expect(isTrackedStatus(s)).toBe(false);
    }
  });
});
