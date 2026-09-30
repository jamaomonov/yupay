// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider, useTranslations } from "next-intl";
import { expect, it } from "vitest";

import { countUnit } from "./skin-landing";
import en from "../../../../packages/i18n/locales/en/web.json";
import ru from "../../../../packages/i18n/locales/ru/web.json";
import uz from "../../../../packages/i18n/locales/uz/web.json";

/** Prints a landing's count line, the way the category page builds it. */
function Count({ category, count }: { category: string; count: number }) {
  const t = useTranslations("web.skins");
  return <p>{t("landing.count", { unit: countUnit(category), count })}</p>;
}

/** Prints a category's meta description, the way the category page builds it. */
function Description({ name, category }: { name: string; category: string }) {
  const t = useTranslations("web.skins");
  const inline =
    category === "agents"
      ? t("landing.agentsInline")
      : t("landing.categoryInline", { name: name.toLocaleLowerCase("ru") });
  return (
    <p>
      {t("landing.description", {
        name: inline,
        items: t("landing.count", { unit: countUnit(category), count: 3 }),
        price: "446 300 сум",
      })}
    </p>
  );
}

function inLocale(locale: string, messages: typeof ru, ui: React.ReactNode) {
  return render(
    <NextIntlClientProvider locale={locale} messages={{ web: messages }}>
      {ui}
    </NextIntlClientProvider>,
  );
}

it.each([
  ["cases", 394, "394 кейса"],
  ["agents", 63, "63 агента"],
  ["music-kits", 5, "5 наборов музыки"],
  ["knives", 21, "21 скин"],
])("counts %s as what they are (ru)", (category, count, text) => {
  inLocale("ru", ru, <Count category={category} count={count} />);
  expect(screen.getByText(text)).toBeInTheDocument();
});

it("counts in English and Uzbek too", () => {
  inLocale("en", en as typeof ru, <Count category="cases" count={1} />);
  expect(screen.getByText("1 case")).toBeInTheDocument();
  inLocale("uz", uz as typeof ru, <Count category="keys" count={12} />);
  expect(screen.getByText("12 ta kalit")).toBeInTheDocument();
});

it("writes a category in running text in lower case with КС2, agents in the accusative", () => {
  inLocale("ru", ru, <Description name="Ножи" category="knives" />);
  expect(
    screen.getByText(
      "Купить ножи КС2 в Узбекистане: 3 скина от 446 300 сум. Оплата в сумах, обмен в Steam за минуту.",
    ),
  ).toBeInTheDocument();
  inLocale("ru", ru, <Description name="Агенты" category="agents" />);
  expect(screen.getByText(/^Купить агентов КС2 в Узбекистане/)).toBeInTheDocument();
});
