import { expect, test } from "@playwright/test";

import type { APIRequestContext } from "@playwright/test";

/**
 * Two redirects live in the same middleware and must not be confused, because
 * the difference is the whole point of the status code.
 *
 * `/ru/x` → `/x` is deterministic and permanent: the prefix is never coming
 * back. Answered with 307, Search Console keeps the prefixed URL in its queue
 * and re-reports it as a redirect page instead of dropping it — which is what
 * it was doing for six URLs before this.
 *
 * `/x` → `/en/x` depends on who is asking. It must stay temporary, or the first
 * English visitor teaches every cache in between that the Russian page moved.
 *
 * Every check runs in its OWN request context. next-intl remembers a visitor's
 * locale in a cookie, so a shared context makes each request depend on the one
 * before it — which is correct behaviour for a returning visitor and useless
 * for testing what a first-time crawler sees.
 */

/**
 * Context options. `baseURL` is omitted rather than passed as `undefined`:
 * under `exactOptionalPropertyTypes` an explicit undefined is not the same as
 * an absent key, and Playwright wants the key absent.
 */
function contextOptions(baseURL: string | undefined, acceptLanguage: string) {
  return {
    ...(baseURL !== undefined ? { baseURL } : {}),
    extraHTTPHeaders: { "Accept-Language": acceptLanguage },
  };
}

async function probe(
  make: () => Promise<APIRequestContext>,
  path: string,
): Promise<{ status: number; location: string }> {
  const ctx = await make();
  try {
    const res = await ctx.get(path, { maxRedirects: 0 });
    return { status: res.status(), location: res.headers().location ?? "" };
  } finally {
    await ctx.dispose();
  }
}

test("the default-locale prefix redirects permanently", async ({ playwright, baseURL }) => {
  const fresh = () => playwright.request.newContext(contextOptions(baseURL, "ru-RU"));
  for (const path of ["/ru/store/steam", "/ru/legal/imprint", "/ru"]) {
    const { status, location } = await probe(fresh, path);
    expect(status, `${path} must be a permanent redirect`).toBe(308);
    expect(location).not.toContain("/ru");
  }
});

test("language detection stays a temporary redirect", async ({ playwright, baseURL }) => {
  const { status } = await probe(
    () => playwright.request.newContext(contextOptions(baseURL, "en-US,en;q=0.9")),
    "/store/steam",
  );
  // 200 or 307 are both fine depending on whether locale detection is on. What
  // must never happen is a PERMANENT redirect, which would pin one visitor's
  // language onto a URL everyone shares.
  expect([200, 307]).toContain(status);
});

test("a first-time visitor gets each locale served directly", async ({ playwright, baseURL }) => {
  for (const [path, lang] of [
    ["/store/steam", "ru-RU"],
    ["/en/store/steam", "en-US"],
    ["/uz/store/steam", "uz-UZ"],
  ] as const) {
    const { status } = await probe(
      () => playwright.request.newContext(contextOptions(baseURL, lang)),
      path,
    );
    expect(status, `${path} must be served directly`).toBe(200);
  }
});
