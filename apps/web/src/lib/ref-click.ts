/**
 * Counting visits to partner links (`yupay.uz/?ref=CODE`).
 *
 * The partner panel hands out `?ref=` links, and until 2026-10-09 nothing
 * counted them: "how many clicks did my link get" was answered from two weeks
 * of proxy logs. This reports a landing to `POST /affiliate/clicks` once per
 * code per day from this browser.
 *
 * It runs in the browser on purpose: crawlers fetch the link but run no
 * JavaScript, so they never count (Googlebot was 13 of 31 hits on one link).
 * The visitor is a random id kept in local storage; the API stores only its
 * hash. Every failure is swallowed — a lost count must never touch the page.
 */

const VISITOR_KEY = "yp_vid";
const SENT_PREFIX = "yp_ref_sent:";
const CODE_RE = /^[A-Za-z0-9_-]{1,64}$/;

/** The `ref` value of a query string, when it looks like a partner code. */
export function refFrom(search: string): string | null {
  const raw = new URLSearchParams(search).get("ref")?.trim() ?? "";
  return CODE_RE.test(raw) ? raw.toUpperCase() : null;
}

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null; // private mode, blocked site data
  }
}

/** This browser's random visitor id, created on first use. */
export function visitorId(store: Storage | null = storage()): string {
  const make = () =>
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random()
          .toString(36)
          .slice(2)}`;
  try {
    const held = store?.getItem(VISITOR_KEY);
    if (held && held.length >= 16) return held;
    const fresh = make();
    store?.setItem(VISITOR_KEY, fresh);
    return fresh;
  } catch {
    return make();
  }
}

/** Report this landing if it carries `?ref=` and was not reported today. */
export async function reportRefClick(
  apiBase: string,
  loc: { search: string; pathname: string } = window.location,
  today: string = new Date().toISOString().slice(0, 10),
  send: typeof fetch = fetch,
): Promise<boolean> {
  const code = refFrom(loc.search);
  if (!code) return false;
  const store = storage();
  const sentKey = `${SENT_PREFIX}${code}`;
  try {
    if (store?.getItem(sentKey) === today) return false;
  } catch {
    /* storage refused: send anyway, the API dedupes per day */
  }
  try {
    await send(`${apiBase}/api/v1/affiliate/clicks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, visitor_id: visitorId(store), path: loc.pathname }),
      keepalive: true,
      credentials: "omit",
    });
    try {
      store?.setItem(sentKey, today);
    } catch {
      /* fine */
    }
    return true;
  } catch {
    return false; // offline, blocked: a lost count, never a broken page
  }
}
