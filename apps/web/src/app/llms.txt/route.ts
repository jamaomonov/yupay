import { getBrands } from "@/lib/catalog";
import { firstNonEmpty, SITE } from "@/lib/seo";

/**
 * /llms.txt — a machine-readable guide for LLMs and AI assistants
 * (see llmstxt.org). It gives ChatGPT, Perplexity, Claude, Google AI
 * Overviews, etc. a compact map of YuPay: what it is, the live catalog
 * (pulled from the API so it stays current), and the key pages to read.
 * The linked pages carry the full content + structured data.
 *
 * Root-level route (outside [locale]); the i18n middleware skips dotted
 * paths, so this serves cleanly at /llms.txt. Regenerated hourly.
 */
export const revalidate = 3600;

const SUMMARY =
  "YuPay — сервис пополнения игровых валют, подписок, лицензий, гифт-карт и цифровых кодов в Узбекистане, России и СНГ. Оплата в сумах картами Uzcard и Humo через Click, Payme и Uzum; для России — YooKassa, Tinkoff, СБП; также USDT. Доставка моментальная и автоматическая, пополнение по публичному ID/логину — пароль от аккаунта не требуется. Курс прозрачен и виден до оплаты, комиссия сервиса 0%.";

const oneLine = (s: string) => s.replace(/\s+/g, " ").trim();

export async function GET(): Promise<Response> {
  // Never let a catalog hiccup 500 the file — an index without the brand list
  // is still a valid, useful llms.txt.
  const brands = await getBrands("ru").catch(() => []);

  const lines = [
    "# YuPay",
    "",
    `> ${SUMMARY}`,
    "",
    "## Каталог",
    ...brands.map((b) => {
      const desc = firstNonEmpty(b.short_description);
      return `- [${b.name}](${SITE}/store/${b.slug})${desc ? `: ${oneLine(desc)}` : ""}`;
    }),
    "",
    "## Ключевые страницы",
    `- [Каталог](${SITE}/store): все бренды, категории и цены в сумах`,
    "",
    "## Правовое",
    `- [Условия использования](${SITE}/legal/terms)`,
    `- [Политика конфиденциальности](${SITE}/legal/privacy)`,
    `- [Возвраты](${SITE}/legal/refunds)`,
    `- [Реквизиты](${SITE}/legal/imprint)`,
    "",
    "## Заметки",
    "- Языки: русский (ru, основной), английский (en), узбекский (uz) — у каждой страницы есть hreflang-альтернативы.",
    "- Данные о товарах и ценах — в разметке schema.org (Product, Offer, AggregateRating, FAQPage) на страницах брендов.",
    "",
  ];

  return new Response(lines.join("\n"), {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=3600, s-maxage=3600",
    },
  });
}
