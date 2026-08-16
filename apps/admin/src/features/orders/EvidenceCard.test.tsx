// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { EvidenceCard } from "./EvidenceCard";

import type { EvidencePackOut } from "./types";
import type { UseQueryResult } from "@tanstack/react-query";

/**
 * The card holds the only personal data the admin can see — the buyer's IP —
 * and the server audits every fetch of it. So the two things pinned here are
 * that nothing is requested or rendered before the operator asks, and that a
 * pack with no capture reads as "not recorded" rather than as a blank card an
 * operator would report as broken.
 */

const PACK: EvidencePackOut = {
  order_id: "01a004c3-0000-0000-0000-000000000000",
  status: "delivered",
  currency: "UZS",
  total_charged: "134380.00",
  created_at: "2026-08-15T09:31:58Z",
  paid_at: "2026-08-15T09:32:18Z",
  delivered_at: null,
  capture: {
    order_id: "01a004c3-0000-0000-0000-000000000000",
    ip: "203.0.113.7",
    user_agent: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)",
    accept_language: "ru-RU,ru;q=0.9",
    client_hints: { timezone: "Asia/Tashkent", locale: "ru-RU", screen: "390x844" },
    created_at: "2026-08-15T09:31:58Z",
    purge_after: "2028-02-06T09:31:58Z",
  },
  timeline: [],
};

/** Only the fields the card actually reads — a full UseQueryResult is a
 *  40-field union that adds nothing to these assertions. */
function asQuery(over: Partial<UseQueryResult<EvidencePackOut>>): UseQueryResult<EvidencePackOut> {
  return {
    data: undefined,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
    ...over,
  } as UseQueryResult<EvidencePackOut>;
}

it("shows nothing until the operator asks, since the read is audited", () => {
  render(<EvidenceCard revealed={false} onReveal={vi.fn()} query={asQuery({ data: PACK })} />);

  expect(screen.queryByText("203.0.113.7")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Показать контекст/ })).toBeInTheDocument();
});

it("asks the page to reveal (which is what enables the fetch) on click", () => {
  const onReveal = vi.fn();
  render(<EvidenceCard revealed={false} onReveal={onReveal} query={asQuery({})} />);

  fireEvent.click(screen.getByRole("button", { name: /Показать контекст/ }));

  expect(onReveal).toHaveBeenCalledOnce();
});

it("renders the capture once revealed", () => {
  render(<EvidenceCard revealed onReveal={vi.fn()} query={asQuery({ data: PACK })} />);

  expect(screen.getByText("203.0.113.7")).toBeInTheDocument();
  expect(screen.getByText("Asia/Tashkent")).toBeInTheDocument();
  expect(screen.getByText("390x844")).toBeInTheDocument();
  expect(screen.getByText(/iPhone/)).toBeInTheDocument();
});

it("explains a pack with no capture instead of rendering an empty card", () => {
  // Orders placed before the capture shipped have none, and the capture is
  // best-effort by design — it must never be the reason a sale fails.
  const noCapture: EvidencePackOut = { ...PACK, capture: null };
  render(<EvidenceCard revealed onReveal={vi.fn()} query={asQuery({ data: noCapture })} />);

  expect(screen.getByText(/Контекст не записан/)).toBeInTheDocument();
  expect(screen.queryByText("203.0.113.7")).not.toBeInTheDocument();
});

it("offers a retry when the pack fails to load", () => {
  const refetch = vi.fn();
  render(<EvidenceCard revealed onReveal={vi.fn()} query={asQuery({ isError: true, refetch })} />);

  fireEvent.click(screen.getByRole("button", { name: "Повторить" }));

  expect(refetch).toHaveBeenCalledOnce();
});
