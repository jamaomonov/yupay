// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, it, vi } from "vitest";

import { HeroTopUp } from "./HeroTopUp";
import messages from "../../../../../packages/i18n/locales/ru/web.json";

import type { TopUpOffer } from "./QuickTopUpCard";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const base = { pattern: null, rateUzs: 100, min: 1, max: 300, initial: "10" };
const OFFERS: TopUpOffer[] = [
  { ...base, kind: "steam", href: "/store/steam", fieldKey: "steam_login" },
  { ...base, kind: "stars", href: "/store/telegram-stars", fieldKey: "username" },
];

function renderHero() {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      <HeroTopUp offers={OFFERS} locale="ru" />
    </NextIntlClientProvider>,
  );
}

it("leads with Steam, Stars waiting behind it", () => {
  renderHero();
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Пополните Steam");
  expect(screen.getByRole("tab", { name: /Steam/ })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("form", { name: "Пополнение Steam" })).toBeInTheDocument();
  // The card behind is out of the accessibility tree until it comes forward.
  expect(screen.queryByRole("form", { name: "Telegram Stars" })).not.toBeInTheDocument();
});

it("brings Stars forward and swaps the headline with it", () => {
  renderHero();
  fireEvent.click(screen.getByRole("tab", { name: /Telegram Stars/ }));
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Купите Stars");
  expect(screen.getByRole("form", { name: "Telegram Stars" })).toBeInTheDocument();
  expect(screen.queryByRole("form", { name: "Пополнение Steam" })).not.toBeInTheDocument();
});

it("switches with the arrow keys on the tabs", () => {
  renderHero();
  fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowRight" });
  expect(screen.getByRole("tab", { name: /Telegram Stars/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowRight" });
  expect(screen.getByRole("tab", { name: /Steam/ })).toHaveAttribute("aria-selected", "true");
});
