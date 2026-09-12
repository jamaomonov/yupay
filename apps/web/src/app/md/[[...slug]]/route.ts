import { LOCALES } from "@yupay/i18n";

import { blogIndexMarkdown, blogPostMarkdown } from "@/lib/blog-markdown";
import { brandMarkdown, homeMarkdown, howToMarkdown, storeMarkdown } from "@/lib/markdown";

/**
 * Markdown content-negotiation endpoint. The middleware rewrites supported
 * pages here when the request carries `Accept: text/markdown` (home, /store,
 * /store/<brand>, /blog, /blog/<slug>), so browsers keep HTML while agents
 * get Markdown. The path arrives as /md[/<locale>]/<rest> — we peel the
 * optional locale and dispatch.
 */
export const revalidate = 300;

/** Peel an optional leading locale segment; defaults to ru. */
function splitLocale(seg: string[]): { locale: string; rest: string[] } {
  const first = seg[0];
  if (first !== undefined && (LOCALES as readonly string[]).includes(first)) {
    return { locale: first, rest: seg.slice(1) };
  }
  return { locale: "ru", rest: seg };
}

const md = (body: string, status = 200): Response =>
  new Response(body, {
    status,
    headers: {
      "Content-Type": "text/markdown; charset=utf-8",
      // Same URL serves HTML or Markdown by Accept — let caches key on it.
      Vary: "Accept",
      "Cache-Control": "public, max-age=300, s-maxage=300",
    },
  });

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ slug?: string[] }> },
): Promise<Response> {
  const { locale, rest } = splitLocale((await params).slug ?? []);

  // Home
  if (rest.length === 0) return md(await homeMarkdown(locale));
  // Store index
  if (rest.length === 1 && rest[0] === "store") return md(await storeMarkdown(locale));
  // Brand page
  const brand = rest.length === 2 && rest[0] === "store" ? rest[1] : undefined;
  if (brand !== undefined) {
    const body = await brandMarkdown(locale, brand);
    return body ? md(body) : md("# 404\n\nСтраница не найдена.\n", 404);
  }
  // Brand "how to" guide
  const guide =
    rest.length === 3 && rest[0] === "store" && rest[2] === "how-to" ? rest[1] : undefined;
  if (guide !== undefined) {
    const body = await howToMarkdown(locale, guide);
    return body ? md(body) : md("# 404\n\nСтраница не найдена.\n", 404);
  }
  if (rest.length === 1 && rest[0] === "blog") return md(await blogIndexMarkdown(locale));
  if (rest.length === 2 && rest[0] === "blog" && rest[1] !== undefined) {
    const body = await blogPostMarkdown(locale, rest[1]);
    return body ? md(body) : md("# 404\n\nСтраница не найдена.\n", 404);
  }
  return md("# 404\n\nСтраница не найдена.\n", 404);
}
