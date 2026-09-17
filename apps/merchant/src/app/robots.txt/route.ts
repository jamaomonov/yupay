/**
 * robots.txt as a route handler (not the typed `robots.ts` metadata file) so
 * we can emit Content-Signal directives — a preference declaration the typed
 * MetadataRoute.Robots API can't express. Ported from the storefront's own
 * `apps/web/src/app/robots.txt/route.ts`; only `Host`/`Sitemap` and
 * `DISALLOW` differ.
 *
 * Content-Signal (contentsignals.org): search=yes and ai-input=yes welcome
 * the wholesale program into search and into live AI answers — that's the
 * goal for a page an operator or a developer might ask an assistant about.
 * ai-train=no reserves model-training rights: it isn't needed to be cited in
 * answers and is irreversible. Flip ai-train to yes here if that stance ever
 * changes.
 */
const CONTENT_SIGNAL = "Content-Signal: search=yes, ai-input=yes, ai-train=no";

/** AI assistant / answer-engine crawlers we explicitly welcome to the public
 *  pages, so the program can be surfaced and cited. The cabinet is
 *  crawlable-but-`noindex`, not disallowed — see the comment on `DISALLOW`
 *  below. */
const AI_CRAWLERS = [
  "GPTBot",
  "OAI-SearchBot",
  "ChatGPT-User",
  "ClaudeBot",
  "anthropic-ai",
  "Claude-User",
  "Claude-SearchBot",
  "PerplexityBot",
  "Perplexity-User",
  "Google-Extended",
  "Applebot-Extended",
  "CCBot",
  "cohere-ai",
  "Amazonbot",
  "Meta-ExternalAgent",
];

/**
 * `/cabinet/` is deliberately NOT listed here, same reasoning the
 * storefront's own `robots.txt` gives for `/account/`/`/orders/`: it is
 * private, but it is handled with `noindex` (`cabinet/layout.tsx` sets
 * `robots: NOINDEX`), which requires the page to stay crawlable. Blocking it
 * here instead would leave any already-indexed cabinet URL stuck in the
 * index with the directive unread — and the cabinet *was* indexable until
 * today's blanket `robots: { index: true, follow: true }` on the locale
 * layout was removed, so that is not a hypothetical.
 *
 * The auth screens (`/login`, `/register`, `/reset`, `/forgot`, `/confirm`)
 * are a different case and stay disallowed: `/reset` and `/confirm` carry a
 * single-use token in the query string, and a bot that renders JS would
 * spend it before the real recipient could — the same reason the storefront
 * disallows `/auth/` outright rather than merely `noindex`ing it. `/login`
 * and `/register` carry no token but get the same treatment for consistency
 * with their siblings. Each has a wildcard twin (a leading `*`) covering the
 * locale prefixes; ru has none.
 *
 * `/api/` is gone from this list as of the intent pages. It was the reflex
 * carried over from an app that serves Route Handlers; this one serves none,
 * and `/api` is now a marketing page listed in `SEO_PATHS`. The rule never
 * blocked `/api` itself — robots prefixes are literal, and the trailing slash
 * meant it only ever matched `/api/…` — but it did block `/api/`, the
 * trailing-slash variant an external link may well carry and that Next
 * 308s to the page. A crawler that is disallowed never reads the redirect.
 */
const DISALLOW = [
  "/login",
  "*/login",
  "/register",
  "*/register",
  "/reset",
  "*/reset",
  "/forgot",
  "*/forgot",
  "/confirm",
  "*/confirm",
];

/** One robots.txt group: its user-agent lines, access rules, and content signal. */
function group(agents: string[]): string {
  return [
    ...agents.map((a) => `User-Agent: ${a}`),
    "Allow: /",
    ...DISALLOW.map((d) => `Disallow: ${d}`),
    CONTENT_SIGNAL,
  ].join("\n");
}

export function GET(): Response {
  const body = [
    group(["*"]),
    "",
    group(AI_CRAWLERS),
    "",
    "Host: https://reseller.yupay.uz",
    "Sitemap: https://reseller.yupay.uz/sitemap.xml",
    "",
  ].join("\n");

  return new Response(body, {
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "public, max-age=3600, s-maxage=3600",
    },
  });
}
