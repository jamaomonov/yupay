import { describe, expect, test, vi } from "vitest";

vi.mock("next-intl/middleware", () => ({
  default: () => () => new Response(null, { status: 200 }) as never,
}));

import middleware, { config } from "./middleware";

function request(url: string, headers: Record<string, string> = {}) {
  const req = new Request(url, { headers }) as never as {
    nextUrl: URL & { clone: () => URL };
    headers: Headers;
  };
  const nextUrl = new URL(url) as URL & { clone: () => URL };
  nextUrl.clone = () => new URL(url);
  return { ...req, nextUrl, headers: new Headers(headers) } as never;
}

/**
 * An RSC flight payload must never be storable by a shared cache.
 *
 * Production served one as the document for every visitor of /store: Next
 * fetches `/store?_rsc=<hash>` during client-side navigation and gets back
 * `text/x-component`, and the edge — told to ignore the query string so that ad
 * clicks with `?utm_source=…&fbclid=…` collapse to one entry — stored that
 * response under the key for the plain page. The whole storefront then answered
 * with raw flight data.
 *
 * The edge config is fixed, but a cache header is the guard that does not
 * depend on one dashboard setting being right.
 */
describe("RSC responses are not shareable", () => {
  test("an RSC request is marked private", () => {
    const res = middleware(request("https://yupay.uz/store?_rsc=abc", { RSC: "1" }));
    expect(res.headers.get("cache-control")).toMatch(/private/);
  });

  test("the marker is the RSC header, not only the query param", () => {
    const res = middleware(request("https://yupay.uz/store", { RSC: "1" }));
    expect(res.headers.get("cache-control")).toMatch(/private/);
  });

  test("and not the query param alone, which a visitor could type", () => {
    const res = middleware(request("https://yupay.uz/store?_rsc=abc"));
    expect(res.headers.get("cache-control")).toMatch(/private/);
  });

  test("an ordinary document is left alone, so the edge can still cache it", () => {
    // The whole point of the edge cache: 99% of ad clicks must not reach the
    // origin. Marking documents private would undo that.
    const res = middleware(request("https://yupay.uz/store"));
    expect(res.headers.get("cache-control")).toBeNull();
  });
});

/**
 * The link-preview cards (`app/og/<locale>/...`) carry their locale in the
 * path already. Through the i18n middleware `/og/ru/store/x` would be pushed
 * under `/ru` (a 404) and a chat crawler would get no picture.
 */
describe("link-preview cards bypass the i18n middleware", () => {
  const matches = (path: string) => config.matcher.some((m) => new RegExp(`^${m}$`).test(path));

  test("/og/... is not matched", () => {
    expect(matches("/og/ru/store/pubg-mobile")).toBe(false);
    expect(matches("/og/en/skins/ak-47-redline-field-tested")).toBe(false);
  });

  test("pages still are, including a slug that starts with og", () => {
    expect(matches("/store/pubg-mobile")).toBe(true);
    expect(matches("/ogame")).toBe(true);
  });
});
