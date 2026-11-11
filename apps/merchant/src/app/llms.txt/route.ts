import { CATALOG_BRANDS, CATALOG_SKUS, formatCount } from "@/lib/brands";
import { OPENAPI_URL, SITE } from "@/lib/seo";

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
 * The best-known brands of the wholesale catalogue, hand-kept — the catalogue
 * itself is behind sign-up. `lib/brands.ts` holds the dated size of the whole
 * catalogue, printed below. Keep the list in step with the landing's own
 * catalogue copy (`merchant.landing.sectionTopupsBody` / `sectionVouchersBody`).
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
    "# YuPay Reseller",
    "",
    "> Обновлено: 2026-11-11.",
    "",
    `> YuPay Reseller (${SITE.replace("https://", "")}) — оптовая закупка пополнений игр, ваучеров и подарочных карт для перепродажи. Аудитория: владельцы Telegram-каналов и магазинов в Узбекистане, России и СНГ, а также разработчики, которым нужен API автоматического пополнения. Регистрация по e-mail, ID игрока проверяется до оплаты и возвращает никнейм, выдача автоматическая — обычно 1–2 минуты, если не выдалось — деньги возвращаются автоматически. Заказ делается из кабинета или через HTTP API с одним ключом (Authorization: Bearer). Это НЕ партнёрская программа partners.yupay.uz (там вознаграждение с заказов приведённых покупателей).`,
    "",
    "## Что можно закупать",
    `- Каталог: ${formatCount("ru", CATALOG_BRANDS)}+ брендов, ${formatCount("ru", CATALOG_SKUS)}+ позиций — пополнения игр, подарочные карты и ваучеры, Telegram Stars и Premium, Steam.`,
    `- В том числе: ${BRANDS}`,
    "- Как платить: предоплатой в кабинете — в сумах или USDT.",
    "",
    "## Для разработчиков",
    `- [Обзор API](${SITE}/api)`,
    `- [Быстрый старт](${SITE}/docs/quickstart)`,
    `- [Авторизация: Authorization: Bearer ypk_…](${SITE}/docs/authentication)`,
    `- [Вебхуки](${SITE}/docs/webhooks)`,
    `- [Ошибки: RFC 7807](${SITE}/docs/errors)`,
    `- OpenAPI 3.1: ${OPENAPI_URL}`,
    "- Эндпоинты: GET /merchant/v1/me · GET /catalog · POST /orders · GET /orders/{merchant_order_id} · POST /validate/player · GET /transactions",
    "",
    "## Ключевые страницы",
    `- [Для Telegram-каналов](${SITE}/telegram)`,
    `- [Вопросы](${SITE}/faq)`,
    `- [Публичная оферта](${SITE}/offer)`,
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
