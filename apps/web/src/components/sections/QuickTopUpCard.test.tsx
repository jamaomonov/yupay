// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, it, vi } from "vitest";

import { QuickTopUpCard, type TopUpOffer } from "./QuickTopUpCard";
import messages from "../../../../../packages/i18n/locales/ru/web.json";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const STEAM: TopUpOffer = {
  kind: "steam",
  href: "/store/steam",
  fieldKey: "steam_login",
  pattern: "^[A-Za-z0-9_-]{3,64}$",
  rateUzs: 12800,
  min: 1,
  max: 300,
  initial: "10",
};
const STARS: TopUpOffer = {
  kind: "stars",
  href: "/store/telegram-stars",
  fieldKey: "username",
  pattern: "^@?[A-Za-z][A-Za-z0-9_]{4,31}$",
  rateUzs: 200,
  min: 50,
  max: 15000,
  initial: "100",
};

function renderCard(offer: TopUpOffer) {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      <QuickTopUpCard offer={offer} locale="ru" />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  push.mockReset();
});

it("prices a Steam amount in soʻm and hands login and amount to the Steam page", () => {
  renderCard(STEAM);
  expect(screen.getByText(/128\s000 сум/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Логин Steam"), { target: { value: " gaben_42 " } });
  fireEvent.click(screen.getByRole("button", { name: /Пополнить/ }));
  expect(push).toHaveBeenCalledWith("/store/steam?steam_login=gaben_42&amount=10");
});

it("refuses a Steam login that is not one and says why", () => {
  renderCard(STEAM);
  fireEvent.change(screen.getByLabelText("Логин Steam"), { target: { value: "a@b.c" } });
  fireEvent.click(screen.getByRole("button", { name: /Пополнить/ }));
  expect(push).not.toHaveBeenCalled();
  expect(screen.getByText(/Латиница, цифры/)).toBeInTheDocument();
});

it("prices stars per star and hands the username to the Stars page", () => {
  renderCard(STARS);
  fireEvent.change(screen.getByLabelText("Сколько звёзд"), { target: { value: "250" } });
  expect(screen.getByText(/50\s000 сум/)).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Юзернейм в Telegram"), {
    target: { value: "@durov" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Купить Stars/ }));
  expect(push).toHaveBeenCalledWith("/store/telegram-stars?username=%40durov&amount=250");
});

it("refuses a fraction of a star", () => {
  renderCard(STARS);
  fireEvent.change(screen.getByLabelText("Сколько звёзд"), { target: { value: "100.5" } });
  expect(screen.getByText(/Целое число, от 50 до 15/)).toBeInTheDocument();
});

it("shows the rails it accepts and falls back to a link without a rate", () => {
  renderCard({ ...STEAM, rateUzs: null });
  expect(screen.getByText("Мы принимаем")).toBeInTheDocument();
  expect(screen.getByAltText("Payme")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Открыть пополнение Steam/ })).toHaveAttribute(
    "href",
    "/store/steam",
  );
});
