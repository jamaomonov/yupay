// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import { SkinTradeCard } from "./SkinTradeCard";
import messages from "../../../../../packages/i18n/locales/ru/web.json";

import type { SkinTradeOut } from "@/lib/orders-types";

const base: SkinTradeOut = {
  state: "buying",
  offer_url: null,
  send_until: null,
  release_date: null,
  seller: null,
  reason_code: null,
};

function card(over: Partial<SkinTradeOut>) {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      <SkinTradeCard trade={{ ...base, ...over }} locale="ru" />
    </NextIntlClientProvider>,
  );
}

describe("SkinTradeCard", () => {
  it("says the offer is on its way while buying", () => {
    card({});
    expect(screen.getByText(/обмен придёт в Steam/)).toBeInTheDocument();
  });

  it("links the sent offer and names the seller", () => {
    card({
      state: "offer_sent",
      offer_url: "https://steamcommunity.com/tradeoffer/9393511289/",
      send_until: new Date(Date.now() + 25 * 60_000).toISOString(),
      seller: { name: "darpan6awx", avatar_url: null, level: 12, joined_at: null },
    });
    expect(screen.getByRole("link", { name: "Открыть обмен в Steam" })).toHaveAttribute(
      "href",
      "https://steamcommunity.com/tradeoffer/9393511289/",
    );
    expect(screen.getByText("darpan6awx")).toBeInTheDocument();
    expect(screen.getByText(/Примите до/)).toBeInTheDocument();
  });

  it("says received and until when Steam protects it", () => {
    card({ state: "accepted", release_date: "2026-10-05T16:00:00Z" });
    expect(screen.getByText("Получено")).toBeInTheDocument();
    expect(screen.getByText(/Steam защищает обмен до/)).toBeInTheDocument();
  });

  it("says the money is back for a declined offer", () => {
    card({ state: "failed", reason_code: "not_accepted" });
    expect(screen.getByText(/деньги вернулись на баланс/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Открыть баланс" })).toBeInTheDocument();
  });

  it("never promises a refund for a purchase support must check", () => {
    card({ state: "failed", reason_code: "support" });
    expect(screen.getByText(/напишите в поддержку/)).toBeInTheDocument();
    expect(screen.queryByText(/вернулись/)).not.toBeInTheDocument();
  });
});
