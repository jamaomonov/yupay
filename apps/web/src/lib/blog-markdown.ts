/**
 * Markdown views of the public blog for ``Accept: text/markdown``.
 *
 * The body has already passed the API allowlist. This file only rewrites those
 * tags so an agent can read the same article without parsing the HTML page.
 */

import { getPublishedPost, listPublishedPosts, type BlogPostDetail } from "./blog";
import { localeUrl, SITE } from "./seo";

interface Labels {
  indexTitle: string;
  indexLead: string;
  faqs: string;
  buy: (name: string) => string;
  onSite: string;
}

const LABELS = {
  ru: {
    indexTitle: "Блог YuPay",
    indexLead: "Гайды и новости по играм, которые мы продаём.",
    faqs: "Вопросы",
    buy: (name) => `Пополнить ${name}`,
    onSite: "Статья на сайте",
  },
  en: {
    indexTitle: "YuPay blog",
    indexLead: "Guides and news about the games we sell.",
    faqs: "Questions",
    buy: (name) => `Top up ${name}`,
    onSite: "Read on the site",
  },
  uz: {
    indexTitle: "YuPay blogi",
    indexLead: "Sotadigan oʻyinlarimiz boʻyicha qoʻllanmalar va yangiliklar.",
    faqs: "Savollar",
    buy: (name) => `${name} ni toʻldirish`,
    onSite: "Saytdagi maqola",
  },
} as const satisfies Record<"ru" | "en" | "uz", Labels>;

function labels(locale: string): Labels {
  if (locale === "en" || locale === "uz") return LABELS[locale];
  return LABELS.ru;
}

function decode(text: string): string {
  return text
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&#(\d+);/g, (_, n: string) => String.fromCodePoint(Number(n)));
}

function absUrl(href: string): string {
  if (href.startsWith("http://") || href.startsWith("https://")) return href;
  if (href.startsWith("/")) return `${SITE}${href}`;
  return href;
}

function inline(html: string): string {
  let s = html;
  s = s.replace(/<img\b([^>]*)\/?>/gi, (_m, attrs: string) => {
    const src = /src="([^"]*)"/i.exec(attrs)?.[1] ?? "";
    const alt = /alt="([^"]*)"/i.exec(attrs)?.[1] ?? "";
    return `![${decode(alt)}](${absUrl(src)})`;
  });
  s = s.replace(
    /<a\b[^>]*href="([^"]*)"[^>]*>([\s\S]*?)<\/a>/gi,
    (_m, href: string, text: string) => `[${inline(text)}](${absUrl(href)})`,
  );
  s = s.replace(/<(strong|b)>([\s\S]*?)<\/\1>/gi, "**$2**");
  s = s.replace(/<(em|i)>([\s\S]*?)<\/\1>/gi, "*$2*");
  s = s.replace(/<code>([\s\S]*?)<\/code>/gi, "`$1`");
  s = s.replace(/<br\s*\/?>/gi, "\n");
  return decode(s.replace(/<\/?(?:p|span)[^>]*>/gi, "")).trim();
}

function listBlock(inner: string, ordered: boolean): string {
  const items = [...inner.matchAll(/<li\b[^>]*>([\s\S]*?)<\/li>/gi)];
  return items
    .map((row, i) => {
      const mark = ordered ? `${String(i + 1)}.` : "-";
      return `${mark} ${inline(row[1] ?? "")}`;
    })
    .join("\n");
}

function tableBlock(html: string): string {
  const rows = [...html.matchAll(/<tr\b[^>]*>([\s\S]*?)<\/tr>/gi)];
  const parsed = rows.map((row) =>
    [...(row[1] ?? "").matchAll(/<(th|td)\b[^>]*>([\s\S]*?)<\/\1>/gi)].map((cell) =>
      inline(cell[2] ?? "").replace(/\|/g, "\\|"),
    ),
  );
  if (parsed.length === 0) return "";
  const width = Math.max(...parsed.map((r) => r.length));
  const pad = (row: string[]): string[] => {
    const next = [...row];
    while (next.length < width) next.push("");
    return next;
  };
  const line = (row: string[]): string => `| ${pad(row).join(" | ")} |`;
  const [head, ...body] = parsed;
  const header = head ?? [];
  const sep = `| ${pad(header)
    .map(() => "---")
    .join(" | ")} |`;
  return [line(header), sep, ...body.map(line)].join("\n");
}

/** Allowlisted article HTML → Markdown. Relative hrefs become absolute. */
export function htmlToMarkdown(html: string): string {
  const fences: string[] = [];
  let s = html.replace(/<pre\b[^>]*>([\s\S]*?)<\/pre>/gi, (_m, inner: string) => {
    const code = decode(inner.replace(/<\/?code\b[^>]*>/gi, "")).replace(/\n$/, "");
    fences.push(`\`\`\`\n${code}\n\`\`\``);
    return `\n\n%%FENCE${String(fences.length - 1)}%%\n\n`;
  });
  s = s.replace(
    /<table\b[^>]*>([\s\S]*?)<\/table>/gi,
    (_m, inner: string) => `\n\n${tableBlock(inner)}\n\n`,
  );
  s = s.replace(
    /<ul\b[^>]*>([\s\S]*?)<\/ul>/gi,
    (_m, inner: string) => `\n\n${listBlock(inner, false)}\n\n`,
  );
  s = s.replace(
    /<ol\b[^>]*>([\s\S]*?)<\/ol>/gi,
    (_m, inner: string) => `\n\n${listBlock(inner, true)}\n\n`,
  );
  s = s.replace(/<blockquote\b[^>]*>([\s\S]*?)<\/blockquote>/gi, (_m, inner: string) => {
    const text = inline(inner)
      .split("\n")
      .map((line) => `> ${line}`.trimEnd())
      .join("\n");
    return `\n\n${text}\n\n`;
  });
  s = s.replace(
    /<h2\b[^>]*>([\s\S]*?)<\/h2>/gi,
    (_m, inner: string) => `\n\n## ${inline(inner)}\n\n`,
  );
  s = s.replace(
    /<h3\b[^>]*>([\s\S]*?)<\/h3>/gi,
    (_m, inner: string) => `\n\n### ${inline(inner)}\n\n`,
  );
  s = s.replace(/<p\b[^>]*>([\s\S]*?)<\/p>/gi, (_m, inner: string) => `\n\n${inline(inner)}\n\n`);
  s = s.replace(/<hr\s*\/?>/gi, "\n\n---\n\n");
  s = s.replace(/<thead\b[^>]*>|<\/thead>|<tbody\b[^>]*>|<\/tbody>/gi, "");
  s = inline(s).replace(/<\/?[a-zA-Z][^>]*>/g, "");
  s = s.replace(/%%FENCE(\d+)%%/g, (_m, i: string) => fences[Number(i)] ?? "");
  return s.replace(/\n{3,}/g, "\n\n").trim();
}

export async function blogIndexMarkdown(locale: string): Promise<string> {
  const L = labels(locale);
  const page = await listPublishedPosts(locale).catch(() => ({ items: [], next_cursor: null }));
  const lines = [`# ${L.indexTitle}`, ``, L.indexLead, ``];
  for (const item of page.items) {
    const url = localeUrl(locale, `/blog/${item.slug}`);
    const extra = item.excerpt ? `: ${item.excerpt}` : "";
    lines.push(`- [${item.title}](${url})${extra}`);
  }
  lines.push(``);
  return lines.join("\n");
}

export async function blogPostMarkdown(locale: string, slug: string): Promise<string | null> {
  const post = await getPublishedPost(slug, locale).catch(() => null);
  if (!post) return null;
  return renderPost(locale, post);
}

function renderPost(locale: string, post: BlogPostDetail): string {
  const L = labels(locale);
  const url = localeUrl(locale, `/blog/${post.slug}`);
  const out: string[] = [`# ${post.title}`, ``];
  if (post.excerpt) out.push(`> ${post.excerpt}`, ``);
  if (post.cover_image_url) {
    out.push(`![${post.title}](${post.cover_image_url})`, ``);
  }
  const body = htmlToMarkdown(post.body_html);
  if (body) out.push(body, ``);
  if (post.faqs.length > 0) {
    out.push(`## ${L.faqs}`, ``);
    for (const faq of post.faqs) {
      out.push(`### ${faq.question}`, ``, faq.answer, ``);
    }
  }
  if (post.show_buy_card) {
    const store = localeUrl(locale, `/store/${post.primary_brand.slug}`);
    out.push(`[${L.buy(post.primary_brand.name)}](${store})`, ``);
  }
  out.push(`[${L.onSite}](${url})`, ``);
  return out.join("\n");
}
