import { expect, test, vi } from "vitest";

vi.mock("./catalog", () => ({
  getBrands: () =>
    Promise.resolve([
      { name: "Steam", slug: "steam", short_description: "Пополнение Steam за сумы" },
    ]),
  getBrandDetail: () =>
    Promise.resolve({
      name: "Steam",
      short_description: "Пополнение Steam за сумы",
      description: null,
      highlights: ["0% комиссии", "Без пароля"],
      instructions: "Шаг 1\nШаг 2",
      faqs: [{ id: "1", question: "Есть ли комиссия?", answer: "Нет, 0%." }],
      products: [{ slug: "steam-wallet" }],
    }),
  getProductDetail: () =>
    Promise.resolve({
      name: "Кошелёк Steam",
      required_fields: [
        {
          key: "steam_login",
          type: "text",
          required: true,
          label: { ru: "Логин Steam" },
          help_text: { ru: "Откройте Steam и войдите." },
        },
      ],
      skus: [
        {
          variable_amount: true,
          min_amount_usd: "1.000000",
          max_amount_usd: "300.000000",
          display_price: { amount: "12866" },
        },
      ],
    }),
}));

import { brandMarkdown, homeMarkdown, howToMarkdown } from "./markdown";

test("home markdown lists brands as links under a heading", async () => {
  const out = await homeMarkdown("ru");
  expect(out).toContain("# YuPay");
  expect(out).toContain("## Каталог");
  expect(out).toContain("[Steam](https://yupay.uz/store/steam): Пополнение Steam за сумы");
});

test("brand markdown carries description, highlights, prices and FAQ", async () => {
  const out = await brandMarkdown("ru", "steam");
  expect(out).not.toBeNull();
  expect(out).toContain("# Steam");
  expect(out).toContain("**Преимущества:** 0% комиссии · Без пароля");
  // Variable amount renders whole dollars + rate, not raw decimals.
  expect(out).toContain("Любая сумма $1–$300");
  expect(out).not.toContain("300.000000");
  expect(out).toContain("## Частые вопросы");
  expect(out).toContain("### Есть ли комиссия?");
});

test("how-to markdown uses a guide title and step/price/faq sections", async () => {
  const out = await howToMarkdown("ru", "steam");
  expect(out).not.toBeNull();
  expect(out).toContain("# Как пополнить Steam в Узбекистане");
  expect(out).toContain("## Пошаговая инструкция");
  expect(out).toContain("## Цены и номиналы");
  expect(out).toContain("## Частые вопросы");
});

test("keeps a numbered how-to as a list, not one run-on line", async () => {
  // `oneLine` collapses every whitespace run, which is right for a one-line
  // list description and wrong here: on prod the Steam gifts hub rendered
  // "1. Найдите игру… 2. Выберите издание… 3. Вставьте ссылку…" as a single
  // paragraph. The steps survived; the structure did not — and structure is
  // the whole reason we serve Markdown to agents rather than stripped HTML.
  const { brandMarkdown } = await import("./markdown");
  const md = await brandMarkdown("ru", "steam");

  expect(md).toContain("Шаг 1\nШаг 2");
  expect(md).not.toContain("Шаг 1 Шаг 2");
});
