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
 *  pages (never /api or /cabinet), so the program can be surfaced and cited. */
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
 * `/cabinet/` is disallowed outright rather than merely `noindex`ed: it is a
 * signed-in, client-rendered area with nothing for a crawler to read, so
 * there is no reason to spend crawl budget fetching it. The auth screens
 * (`/login`, `/register`, `/reset`, `/forgot`, `/confirm`) carry the same
 * treatment as the storefront's `/auth/` — `/reset` and `/confirm` in
 * particular carry a single-use token in the query string, and a bot that
 * renders JS would spend it before the real recipient could. Each has a
 * wildcard twin (a leading `*`) covering the locale prefixes; ru has none.
 */
const DISALLOW = [
  "/api/",
  "/cabinet/",
  "*/cabinet/",
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
