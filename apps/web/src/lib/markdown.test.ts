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

import { brandMarkdown, homeMarkdown } from "./markdown";

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
