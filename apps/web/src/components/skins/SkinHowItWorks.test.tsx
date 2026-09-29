// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it } from "vitest";

import { SkinHowItWorks } from "./SkinHowItWorks";
import en from "../../../../../packages/i18n/locales/en/web.json";
import ru from "../../../../../packages/i18n/locales/ru/web.json";
import uz from "../../../../../packages/i18n/locales/uz/web.json";

function show(locale: string, messages: typeof ru) {
  render(
    <NextIntlClientProvider locale={locale} messages={{ web: messages }}>
      <SkinHowItWorks />
    </NextIntlClientProvider>,
  );
}

describe("SkinHowItWorks", () => {
  it("walks the buyer from the trade link to the refund, in order", () => {
    show("ru", ru);
    expect(screen.getByRole("heading", { name: "Как проходит покупка" })).toBeInTheDocument();
    const steps = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(steps).toHaveLength(5);
    expect(steps[0]).toMatch(/Steam Guard/);
    expect(steps[2]).toMatch(/30 минут/);
    expect(steps[3]).toMatch(/7 дней/);
    expect(steps[4]).toMatch(/баланс YuPay/);
  });

  it.each([
    ["en", en],
    ["uz", uz],
  ] as const)("is translated in %s", (locale, messages) => {
    show(locale, messages);
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    expect(document.body.textContent).not.toMatch(/web\.skins\.how/);
  });
});
