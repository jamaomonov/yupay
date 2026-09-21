import { listPublishedPosts } from "@/lib/blog";
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
  const posts = await listPublishedPosts("ru").catch(() => ({ items: [], next_cursor: null }));

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
    "## Гайды и новости",
    ...posts.items.slice(0, 20).map((p) => `- [${p.title}](${SITE}/blog/${p.slug})`),
    "",
    "## Ключевые страницы",
    `- [Каталог](${SITE}/store): все бренды, категории и цены в сумах`,
    `- [Блог](${SITE}/blog): гайды и новости по брендам каталога`,
    "",
    "## Для бизнеса",
    "- [YuPay Reseller](https://reseller.yupay.uz): оптовая закупка пополнений, ваучеров и подарочных карт для перепродажи. Проверка ID игрока до оплаты, выдача 1–2 минуты.",
    "- [Merchant API](https://reseller.yupay.uz/api): HTTP API автоматического пополнения — 6 эндпоинтов, HMAC-подпись, вебхуки, проверка ID игрока. OpenAPI: https://api.yupay.uz/merchant/openapi.json",
    "- [Партнёрская программа](https://partners.yupay.uz): 2% с заказов приведённых покупателей (это другой продукт — не оптовая закупка).",
    "",
    "## Правовое",
    `- [Все документы](${SITE}/legal)`,
    `- [Публичная оферта](${SITE}/legal/terms)`,
    `- [Пользовательское соглашение](${SITE}/legal/agreement)`,
    `- [Политика конфиденциальности](${SITE}/legal/privacy)`,
    `- [Возвраты](${SITE}/legal/refunds)`,
    `- [Реквизиты](${SITE}/legal/imprint)`,
    "",
    "## Заметки",
    "- Языки: русский (ru, основной), английский (en), узбекский (uz) — у каждой страницы есть hreflang-альтернативы.",
    "- Данные о товарах и ценах — в разметке schema.org (Product, Offer, AggregateRating, FAQPage) на страницах брендов.",
    "- Каталог, бренд, /blog и /blog/{slug} отдают Markdown при `Accept: text/markdown`.",
    "",
  ];

  return new Response(lines.join("\n"), {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=3600, s-maxage=3600",
    },
  });
}
