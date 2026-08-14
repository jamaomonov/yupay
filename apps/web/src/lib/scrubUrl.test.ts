import { describe, expect, it } from "vitest";

import { scrubSearchParams, scrubUrl } from "./scrubUrl";

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
