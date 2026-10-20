/**
 * A form's fields handed from one page to the next without a query string.
 *
 * The home page's quick form used to push `/store/steam?steam_login=…&amount=…`.
 * Google Tag Manager reports a History Change with the page URL, so the
 * recipient's Steam login or Telegram username went to Google. The fields now
 * travel in `sessionStorage`, bound to the path they are for and read once.
 * A query string on an external link still works (`PurchasePanel` reads both).
 */
const KEY = "yupay.web.handoff";

function samePath(a: string, b: string): boolean {
  const trim = (p: string) => (p.length > 1 ? p.replace(/\/+$/, "") : p);
  return trim(a) === trim(b);
}

/** Leave `params` for the page at `path` to pick up on arrival. */
export function stashHandoff(path: string, params: URLSearchParams): void {
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify({ path, query: params.toString() }));
  } catch {
    /* storage blocked: the buyer fills the form again */
  }
}

/** The params left for `path`, once; `null` when there are none for it. */
export function takeHandoff(path: string): URLSearchParams | null {
  try {
    const raw = window.sessionStorage.getItem(KEY);
    if (raw === null) return null;
    window.sessionStorage.removeItem(KEY);
    const parsed: unknown = JSON.parse(raw);
    if (
      parsed === null ||
      typeof parsed !== "object" ||
      !("path" in parsed) ||
      !("query" in parsed) ||
      typeof parsed.path !== "string" ||
      typeof parsed.query !== "string" ||
      !samePath(parsed.path, path)
    ) {
      return null;
    }
    return new URLSearchParams(parsed.query);
  } catch {
    return null;
  }
}
