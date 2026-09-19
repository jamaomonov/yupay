import {
  getBrandDetail,
  getBrands,
  getProductDetail,
  type BrandSummary,
  type HelpImage,
  type LocaleMap,
  type SkuOut,
} from "./catalog";
import { firstNonEmpty, formatUzs, SITE } from "./seo";

/**
 * Markdown renderers for content negotiation (Accept: text/markdown). Agents
 * get a clean, link-rich Markdown view of the same catalog data the HTML pages
 * render, which is cheaper and more reliable for LLMs to read and cite than
 * parsing the full page. Browsers keep getting HTML (see middleware).
 *
 * Every builder pulls live catalog data and fails soft — a transient API hiccup
 * yields a smaller-but-valid document, never a 500.
 */

const CURRENCY = "UZS";

const SUMMARY =
  "YuPay — пополнение игровых валют, подписок, лицензий, гифт-карт и цифровых кодов в Узбекистане, России и СНГ. Оплата в сумах картами Uzcard и Humo (Click, Payme, Uzum), для России — YooKassa, Tinkoff, СБП, а также USDT. Доставка моментальная и автоматическая, пополнение по публичному ID/логину — пароль не требуется. Комиссия сервиса 0%, курс виден до оплаты.";

const oneLine = (s: string): string => s.replace(/\s+/g, " ").trim();

/** Picks a locale's string, falling back to ru then the first *non-empty*
 *  translation. The admin's caption/label editors submit all three locale
 *  keys, so an untouched one arrives as `""`, not a missing key — a plain
 *  `??` chain doesn't fall back on that (the same bug the storefront's
 *  "где найти" modal had). */
function localize(m: LocaleMap | null | undefined, locale: string): string | null {
  if (!m) return null;
  const byLocale = m[locale];
  if (byLocale && byLocale.trim().length > 0) return byLocale;
  if (m.ru && m.ru.trim().length > 0) return m.ru;
  return Object.values(m).find((v) => v.trim().length > 0) ?? null;
}

/**
 * A prose block, with its shape intact.
 *
 * `oneLine` is right for a list-item description and wrong for anything
 * longer: `instructions` is a numbered how-to, and collapsing it produced one
 * run-on paragraph reading "1. Найдите игру… 2. Выберите издание…" — the steps
 * were still there, the structure was not, and Markdown is the format we chose
 * precisely so a reader gets the structure.
 *
 * Only horizontal whitespace is squeezed; line breaks survive, so numbered
 * lines stay list items, and runs of blank lines collapse to a single
 * paragraph break.
 */
const block = (s: string): string =>
  s
    .replace(/[^\S\n]+/g, " ")
    .replace(/[^\S\n]*\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

function brandList(brands: BrandSummary[]): string {
  return brands
    .map((b) => {
      const d = firstNonEmpty(b.short_description);
      return `- [${b.name}](${SITE}/store/${b.slug})${d ? `: ${oneLine(d)}` : ""}`;
    })
    .join("\n");
}

/** One catalog line per SKU: a fixed denomination with its som price, or a
 *  variable top-up with its range and per-dollar rate. */
function skuLine(locale: string, s: SkuOut): string {
  if (s.variable_amount) {
    const rate = s.display_price
      ? ` (курс 1 $ = ${formatUzs(locale, Math.round(Number(s.display_price.amount)))})`
      : "";
    // Amounts arrive as decimal strings ("1.000000") — render whole dollars.
    const min = `$${String(Number(s.min_amount_usd ?? "1"))}`;
    const max = s.max_amount_usd ? `–$${String(Number(s.max_amount_usd))}` : "";
    return `- Любая сумма ${min}${max}${rate}`;
  }
  const denom = s.denomination ?? s.sku_code;
  const price = s.display_price
    ? ` — ${formatUzs(locale, Math.round(Number(s.display_price.amount)))}`
    : "";
  return `- ${denom}${price}`;
}

export async function homeMarkdown(locale: string): Promise<string> {
  const brands = await getBrands(locale).catch(() => []);
  return [`# YuPay`, ``, `> ${SUMMARY}`, ``, `## Каталог`, brandList(brands), ``].join("\n");
}

export async function storeMarkdown(locale: string): Promise<string> {
  const brands = await getBrands(locale).catch(() => []);
  return [
    `# Каталог YuPay`,
    ``,
    `Пополнение игр, подписок и цифровых кодов в Узбекистане и СНГ. Цены в сумах, комиссия 0%, доставка моментальная.`,
    ``,
    `## Бренды`,
    brandList(brands),
    ``,
  ].join("\n");
}

/** Locale-aware section headers for the how-to guide markdown. */
interface HowToLabels {
  title: (n: string) => string;
  steps: string;
  where: string;
  /** Placeholder for a step screenshot that carries no caption — an agent
   *  reading Markdown can't see the picture, so a step with no words still
   *  gets a line saying one exists, instead of a silently missing number. */
  screenshot: string;
  prices: string;
  faq: string;
}
const HOWTO_RU: HowToLabels = {
  title: (n) => `Как пополнить ${n} в Узбекистане`,
  steps: "Пошаговая инструкция",
  where: "Где найти ID / логин",
  screenshot: "Скриншот",
  prices: "Цены и номиналы",
  faq: "Частые вопросы",
};
const HOWTO_L: Record<string, HowToLabels> = {
  ru: HOWTO_RU,
  en: {
    title: (n) => `How to top up ${n} in Uzbekistan`,
    steps: "Step by step",
    where: "Where to find your ID / login",
    screenshot: "Screenshot",
    prices: "Prices and denominations",
    faq: "FAQ",
  },
  uz: {
    title: (n) => `${n} ni Oʻzbekistonda qanday toʻldirish`,
    steps: "Bosqichma-bosqich",
    where: "ID / login qayerdan olinadi",
    screenshot: "Skrinshot",
    prices: "Narxlar va nominallar",
    faq: "Koʻp beriladigan savollar",
  },
};

/** Per-brand "how to top up" guide as Markdown (mirrors the /how-to page).
 *  Returns null when the brand doesn't exist (→ 404). */
export async function howToMarkdown(locale: string, slug: string): Promise<string | null> {
  const brand = await getBrandDetail(slug, locale, CURRENCY).catch(() => null);
  if (!brand) return null;
  const L = HOWTO_L[locale] ?? HOWTO_RU;

  const out: string[] = [`# ${L.title(brand.name)}`, ``];
  const intro = firstNonEmpty(brand.short_description, brand.description);
  if (intro) out.push(block(intro), ``);

  if (brand.instructions) out.push(`## ${L.steps}`, block(brand.instructions), ``);

  const products = await Promise.all(
    (brand.products ?? []).map((p) => getProductDetail(p.slug, locale, CURRENCY).catch(() => null)),
  );
  let where: string | null = null;
  let whereImages: HelpImage[] = [];
  for (const p of products) {
    const field = p?.required_fields[0];
    if (!field) continue;
    const text = localize(field.help_text, locale);
    const images = field.help_images ?? [];
    // A field documented only with screenshots (no help_text) still
    // deserves the section — it used to be skipped entirely because this
    // looked at help_text alone.
    if (text || images.length > 0) {
      where = text;
      whereImages = images;
      break;
    }
  }
  if (where || whereImages.length > 0) {
    out.push(`## ${L.where}`);
    if (where) out.push(``, block(where));
    if (whereImages.length > 0) {
      // An agent reading this Markdown can't see the screenshots — the
      // captions are the only part of the walkthrough that survives, so
      // they're rendered as an ordered list rather than dropped.
      out.push(``);
      whereImages.forEach((img, i) => {
        const caption = localize(img.caption, locale);
        out.push(`${String(i + 1)}. ${caption ? oneLine(caption) : L.screenshot}`);
      });
    }
    out.push(``);
  }

  const priced = products.filter(
    (p): p is NonNullable<typeof p> => p !== null && p.skus.length > 0,
  );
  if (priced.length > 0) {
    out.push(`## ${L.prices}`);
    for (const p of priced) {
      out.push(``, `### ${p.name}`);
      for (const s of p.skus) out.push(skuLine(locale, s));
    }
    out.push(``);
  }

  if (brand.faqs && brand.faqs.length > 0) {
    out.push(`## ${L.faq}`);
    for (const f of brand.faqs) out.push(``, `### ${f.question}`, block(f.answer));
    out.push(``);
  }

  out.push(`[${brand.name} — ${SITE}/store/${slug}](${SITE}/store/${slug})`, ``);
  return out.join("\n");
}

/** Full brand page as Markdown: description, highlights, per-SKU prices,
 *  how-to, and FAQ. Returns null when the brand doesn't exist (→ 404). */
export async function brandMarkdown(locale: string, slug: string): Promise<string | null> {
  const brand = await getBrandDetail(slug, locale, CURRENCY).catch(() => null);
  if (!brand) return null;

  const out: string[] = [`# ${brand.name}`, ``];
  const desc = firstNonEmpty(brand.short_description, brand.description);
  if (desc) out.push(block(desc), ``);
  if (brand.highlights && brand.highlights.length > 0) {
    out.push(`**Преимущества:** ${brand.highlights.join(" · ")}`, ``);
  }

  const products = brand.products ?? [];
  const details = await Promise.all(
    products.map((p) => getProductDetail(p.slug, locale, CURRENCY).catch(() => null)),
  );
  const priced = details.filter((p): p is NonNullable<typeof p> => p !== null && p.skus.length > 0);
  if (priced.length > 0) {
    out.push(`## Номиналы и цены`);
    for (const p of priced) {
      out.push(``, `### ${p.name}`);
      for (const s of p.skus) out.push(skuLine(locale, s));
    }
    out.push(``);
  }

  if (brand.instructions) out.push(`## Как пополнить`, block(brand.instructions), ``);

  if (brand.faqs && brand.faqs.length > 0) {
    out.push(`## Частые вопросы`);
    for (const f of brand.faqs) out.push(``, `### ${f.question}`, block(f.answer));
    out.push(``);
  }

  out.push(`[Открыть на сайте](${SITE}/store/${slug})`, ``);
  return out.join("\n");
}
