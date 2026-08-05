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
    const min = `$${Number(s.min_amount_usd ?? "1")}`;
    const max = s.max_amount_usd ? `–$${Number(s.max_amount_usd)}` : "";
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
