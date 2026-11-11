// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { beforeEach, expect, test } from "vitest";

import { TrackEvent } from "./TrackEvent";

import { viewItemEvent } from "@/lib/analytics-events";

beforeEach(() => {
  delete window.dataLayer;
});

const events = (): unknown[] =>
  (window.dataLayer ?? []).filter((e) => typeof e === "object" && e !== null && "event" in e);

test("sends once per key, however often it re-renders", () => {
  const steam = viewItemEvent({ slug: "steam", name: "Steam" });
  const { rerender } = render(<TrackEvent event={steam} dedupeKey="steam" />);
  rerender(<TrackEvent event={{ ...steam }} dedupeKey="steam" />);
  expect(events()).toHaveLength(1);

  rerender(<TrackEvent event={viewItemEvent({ slug: "mlbb", name: "MLBB" })} dedupeKey="mlbb" />);
  expect(events()).toHaveLength(2);
});
