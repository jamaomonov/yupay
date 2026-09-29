// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, expect, it, vi } from "vitest";

import { SteamQuickTopUp } from "./SteamQuickTopUp";
import messages from "../../../../../packages/i18n/locales/ru/web.json";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

function renderForm(rateUzs: number | null = 12800) {
  render(
    <NextIntlClientProvider locale="ru" messages={{ web: messages }}>
      <SteamQuickTopUp
        locale="ru"
        rateUzs={rateUzs}
        minUsd={1}
        maxUsd={300}
        loginPattern="^[A-Za-z0-9_-]{3,64}$"
      />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  push.mockReset();
});

it("prices the amount in soʻm as it is picked", () => {
  renderForm();
  expect(screen.getByText(/128\s000 сум/)).toBeInTheDocument(); // $10 default
  fireEvent.click(screen.getByRole("button", { name: "$50" }));
  expect(screen.getByText(/640\s000 сум/)).toBeInTheDocument();
});

it("hands the login and amount to the Steam page", () => {
  renderForm();
  fireEvent.change(screen.getByLabelText("Логин Steam"), { target: { value: " gaben_42 " } });
  fireEvent.click(screen.getByRole("button", { name: /Пополнить/ }));
  expect(push).toHaveBeenCalledWith("/store/steam?steam_login=gaben_42&amount=10");
});

it("refuses a login that is not one and says why", () => {
  renderForm();
  fireEvent.change(screen.getByLabelText("Логин Steam"), { target: { value: "a@b.c" } });
  fireEvent.click(screen.getByRole("button", { name: /Пополнить/ }));
  expect(push).not.toHaveBeenCalled();
  expect(screen.getByText(/Латиница, цифры/)).toBeInTheDocument();
});

it("falls back to a plain link when the rate is unavailable", () => {
  renderForm(null);
  expect(screen.getByRole("link", { name: /Открыть пополнение Steam/ })).toHaveAttribute(
    "href",
    "/store/steam",
  );
});
