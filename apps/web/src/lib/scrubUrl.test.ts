import { describe, expect, it } from "vitest";

import { scrubScript, scrubSearchParams, scrubUrl } from "./scrubUrl";

describe("scrubUrl", () => {
  it("removes the access token and email from an order magic link", () => {
    const out = scrubUrl("https://yupay.uz/ru/orders/abc?access=eyJ.jwt.sig&email=a%40b.com");
    expect(out).toBe("https://yupay.uz/ru/orders/abc");
    expect(out).not.toContain("access");
    expect(out).not.toContain("email");
    expect(out).not.toContain("eyJ");
  });

  // Yandex's crawl log showed `/en/auth/verify?token=eyJhbGciOi…`: Metrika had
  // reported the email link verbatim, so the crawler went and fetched it. The
  // same param carries the password-reset token.
  it("removes the verify / reset token from an email link", () => {
    expect(scrubUrl("https://yupay.uz/en/auth/verify?token=eyJhbGciOi.jwt.sig")).toBe(
      "https://yupay.uz/en/auth/verify",
    );
    expect(scrubUrl("https://yupay.uz/ru/auth/reset?token=eyJhbGciOi.jwt.sig")).toBe(
      "https://yupay.uz/ru/auth/reset",
    );
  });

  it("keeps non-sensitive params intact", () => {
    const out = scrubUrl("https://yupay.uz/ru/store?ref=tg&access=secret");
    expect(out).toBe("https://yupay.uz/ru/store?ref=tg");
  });

  it("leaves a clean URL unchanged", () => {
    expect(scrubUrl("https://yupay.uz/ru/store/steam")).toBe("https://yupay.uz/ru/store/steam");
  });

  it("does not throw on an unparseable input", () => {
    expect(scrubUrl("not a url")).toBe("not a url");
  });
});

describe("scrubSearchParams", () => {
  it("drops access + email + token, keeps the rest", () => {
    expect(scrubSearchParams("access=x&email=y&token=z&page=2")).toBe("page=2");
  });

  it("returns empty when only sensitive params are present", () => {
    expect(scrubSearchParams("access=x&email=y&token=z")).toBe("");
  });
});

describe("Steam sign-in and recipient params", () => {
  const callback =
    "https://yupay.uz/ru/auth/steam/callback?openid.ns=x&openid.sig=s1g&openid.claimed_id=" +
    "https%3A%2F%2Fsteamcommunity.com%2Fopenid%2Fid%2F7656&openid.response_nonce=n&lang=ru";

  it("drops every openid.* param of the Steam assertion", () => {
    expect(scrubUrl(callback)).toBe("https://yupay.uz/ru/auth/steam/callback?lang=ru");
  });

  it("drops a recipient handed to a product page", () => {
    expect(scrubSearchParams("steam_login=gaben&amount=5")).toBe("amount=5");
    expect(scrubSearchParams("username=%40someone&amount=50")).toBe("amount=50");
  });

  it("the inline snippet scrubs exactly what scrubUrl does", () => {
    const holder = { u: new URL(callback) };
    // The snippet is a string of ES5 that the page inlines; run it as such.
    // eslint-disable-next-line @typescript-eslint/no-implied-eval -- the snippet under test
    const run = new Function("holder", scrubScript("holder.u")) as (h: typeof holder) => void;
    run(holder);
    expect(holder.u.toString()).toBe(scrubUrl(callback));
  });
});
