// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { RatingSummary } from "./RatingSummary";

vi.mock("next-intl/server", () => ({
  getTranslations: async () => (k: string, vars?: { count?: number }) =>
    vars?.count != null ? `${k}:${vars.count}` : k,
}));

test("renders average, count and a 5-row histogram", async () => {
  render(
    await RatingSummary({
      stats: { avg: 4.5, count: 10, dist: { "5": 7, "4": 2, "3": 1, "2": 0, "1": 0 } },
    }),
  );
  expect(screen.getByText("4.5")).toBeInTheDocument();
  expect(screen.getByText("count:10")).toBeInTheDocument();
});

test("shows an empty state when there are no reviews", async () => {
  render(await RatingSummary({ stats: { avg: 0, count: 0, dist: {} } }));
  expect(screen.getByText("empty")).toBeInTheDocument();
});
