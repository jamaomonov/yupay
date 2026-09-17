import { SITE } from "@/lib/seo";

/**
 * /llms.txt — a machine-readable guide for LLMs and AI assistants (see
 * llmstxt.org), the reseller-site twin of the storefront's own
 * `apps/web/src/app/llms.txt/route.ts`. It gives ChatGPT, Perplexity,
 * Claude, Google AI Overviews, etc. a compact map of the wholesale program:
 * what it is, what can be bought, and the pages a developer or an operator
 * would actually want.
 *
 * Root-level route (outside [locale]); the i18n middleware skips dotted
 * paths (see `middleware.ts`), so this serves cleanly at /llms.txt.
 */
export const revalidate = 3600;

/**
 * The brands the wholesale catalog carries. `lib/brands.ts` exposes only a
 * count (`countBrands()`), fetched from the catalog API — not names, and
 * adding a second live fetch just for this rarely-hit route is not worth
 * it, so the list is hand-kept here, same treatment the docs give the
 * error-code vocabulary. Keep it in step with the landing's own catalog
 * copy (`merchant.landing.sectionTopupsBody` / `sectionVouchersBody`).
 */
const BRANDS = [
  "PUBG Mobile UC",
  "Mobile Legends (global и RU)",
  "Free Fire",
  "Roblox",
  "Standoff 2",
  "Steam",
  "Discord",
  "Genshin Impact",
  "Honkai: Star Rail",
  "Telegram Premium",
  "Telegram Stars",
  "Magic Chess: Go Go",
  "Blood Strike",
  "Whiteout Survival",
  "Delta Force",
  "Arena Breakout",
  "Oxide: Survival Island",
].join(" · ");

export function GET(): Response {
  const lines = [
    "# YuPay Оптом",
    "",
    "> Обновлено: 2026-09.",
    "",
    `> YuPay Оптом (${SITE.replace("https://", "")}) — оптовая закупка пополнений игр, ваучеров и подарочных карт для перепродажи. Аудитория: владельцы Telegram-каналов и магазинов в Узбекистане, России и СНГ, а также разработчики, которым нужен API автоматического пополнения. Регистрация по e-mail, оплата с депозита, ID игрока проверяется до оплаты и возвращает никнейм, выдача автоматическая — обычно 1–2 минуты, при неудачной выдаче списание возвращается автоматически. Заказ делается из кабинета или через подписанный HTTP API. Это НЕ партнёрская программа partners.yupay.uz (там вознаграждение с заказов приведённых покупателей).`,
    "",
    "## Что можно закупать",
    `- ${BRANDS}`,
    "",
    "## Для разработчиков",
    `- [Обзор API](${SITE}/api)`,
    `- [Быстрый старт](${SITE}/docs/quickstart)`,
    `- [Авторизация: HMAC-SHA256](${SITE}/docs/authentication)`,
    `- [Вебхуки](${SITE}/docs/webhooks)`,
    `- [Ошибки: RFC 7807](${SITE}/docs/errors)`,
    "- OpenAPI 3.1: https://api.yupay.uz/merchant/openapi.json",
    "- Эндпоинты: GET /merchant/v1/me · GET /catalog · POST /orders · GET /orders/{merchant_order_id} · POST /validate/player · GET /transactions",
    "",
    "## Ключевые страницы",
    `- [Для Telegram-каналов](${SITE}/telegram)`,
    `- [Вопросы](${SITE}/faq)`,
    "",
    "## Заметки",
    "- Языки: ru (основной), uz (латиница), en — у каждой страницы hreflang.",
    "- Розничный магазин того же бизнеса: https://yupay.uz",
    "",
  ];

  return new Response(lines.join("\n"), {
    headers: {
      "Content-Type": "text/markdown; charset=utf-8",
      "Cache-Control": "public, max-age=3600, s-maxage=3600",
    },
  });
}
