import { describe, expect, it } from "vitest";

import { eventChip } from "./blog";

describe("eventChip", () => {
  const now = Date.parse("2026-09-12T12:00:00.000Z");

  it("marks an in-window event live", () => {
    expect(
      eventChip(
        {
          kind: "event",
          event_starts_at: "2026-09-12T00:00:00.000Z",
          event_ends_at: "2026-09-13T00:00:00.000Z",
        },
        now,
      ),
    ).toBe("live");
  });

  it("marks a past event ended", () => {
    expect(
      eventChip(
        {
          kind: "event",
          event_starts_at: "2026-09-01T00:00:00.000Z",
          event_ends_at: "2026-09-02T00:00:00.000Z",
        },
        now,
      ),
    ).toBe("ended");
  });

  it("ignores non-events", () => {
    expect(
      eventChip({ kind: "guide", event_starts_at: null, event_ends_at: null }, now),
    ).toBeNull();
  });
});
