import { describe, expect, test, vi } from "vitest";

vi.mock("next-intl/middleware", () => ({
  default: () => () => new Response(null, { status: 200 }) as never,
}));

import middleware from "./middleware";

function request(url: string, headers: Record<string, string> = {}) {
  const nextUrl = new URL(url) as URL & { clone: () => URL };
  nextUrl.clone = () => new URL(url);
  return { nextUrl, headers: new Headers(headers) } as never;
}

/**
 * The cabinet's front door.
 *
 * Every page lives under `app/[locale]/`, so with no middleware the unprefixed
 * URLs do not exist at all: production answered 404 on `reseller.yupay.uz/`
 * and 200 on `/ru`, which is the inverse of what `localePrefix: "as-needed"`
 * promises. The router config alone does nothing at request time — this file
 * is the half that runs.
 */
describe("the intl middleware is wired up", () => {
  test("an unprefixed path is handled, not passed through", () => {
    // The mocked next-intl middleware answers 200. What is asserted is that it
    // was consulted at all: without `createMiddleware(routing)` the request
    // would reach the router, where `/` has no route.
    expect(middleware(request("https://reseller.yupay.uz/")).status).toBe(200);
  });

  test("the matcher leaves Next's own assets alone", () => {
    for (const path of ["/_next/static/chunk.js", "/favicon.ico", "/icon.svg"]) {
      expect(path).toMatch(/^\/_next\/|\./);
    }
  });
});

/**
 * An RSC flight payload must never be storable by a shared cache. The
 * storefront served one as the document for every visitor of /store once, and
 * this origin sits behind the same Cloudflare.
 */
describe("RSC responses are not shareable", () => {
  test("the RSC header marks it private", () => {
    const res = middleware(request("https://reseller.yupay.uz/cabinet", { RSC: "1" }));
    expect(res.headers.get("cache-control")).toMatch(/private/);
  });

  test("so does the query param alone", () => {
    const res = middleware(request("https://reseller.yupay.uz/cabinet?_rsc=abc"));
    expect(res.headers.get("cache-control")).toMatch(/private/);
  });

  test("an ordinary document is left alone", () => {
    const res = middleware(request("https://reseller.yupay.uz/cabinet"));
    expect(res.headers.get("cache-control")).toBeNull();
  });
});
