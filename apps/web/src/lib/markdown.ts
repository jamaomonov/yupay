import {
  getBrandDetail,
  getBrands,
  getProductDetail,
  type BrandSummary,
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
  prices: string;
  faq: string;
}
const HOWTO_RU: HowToLabels = {
  title: (n) => `Как пополнить ${n} в Узбекистане`,
  steps: "Пошаговая инструкция",
  where: "Где найти ID / логин",
  prices: "Цены и номиналы",
  faq: "Частые вопросы",
};
const HOWTO_L: Record<string, HowToLabels> = {
  ru: HOWTO_RU,
  en: {
    title: (n) => `How to top up ${n} in Uzbekistan`,
    steps: "Step by step",
    where: "Where to find your ID / login",
    prices: "Prices and denominations",
    faq: "FAQ",
  },
  uz: {
    title: (n) => `${n} ni Oʻzbekistonda qanday toʻldirish`,
    steps: "Bosqichma-bosqich",
    where: "ID / login qayerdan olinadi",
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
  if (intro) out.push(oneLine(intro), ``);

  if (brand.instructions) out.push(`## ${L.steps}`, oneLine(brand.instructions), ``);

  const products = await Promise.all(
    (brand.products ?? []).map((p) => getProductDetail(p.slug, locale, CURRENCY).catch(() => null)),
  );
  let where: string | null = null;
  for (const p of products) {
    const h = p?.required_fields[0]?.help_text;
    if (h) {
      where = h[locale] ?? h.ru ?? Object.values(h)[0] ?? null;
      break;
    }
  }
  if (where) out.push(`## ${L.where}`, oneLine(where), ``);

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
    for (const f of brand.faqs) out.push(``, `### ${f.question}`, oneLine(f.answer));
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
  if (desc) out.push(oneLine(desc), ``);
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

  if (brand.instructions) out.push(`## Как пополнить`, oneLine(brand.instructions), ``);

  if (brand.faqs && brand.faqs.length > 0) {
    out.push(`## Частые вопросы`);
    for (const f of brand.faqs) out.push(``, `### ${f.question}`, oneLine(f.answer));
    out.push(``);
  }

  out.push(`[Открыть на сайте](${SITE}/store/${slug})`, ``);
  return out.join("\n");
}
