import { describe, expect, it } from "vitest";

import {
  ORGANIZATION_ID,
  breadcrumbs,
  faqPage,
  organization,
  service,
  techArticle,
  website,
} from "./jsonld";

describe("jsonld builders", () => {
  it("organization points at the storefront's own record", () => {
    const node = organization();
    expect(node["@id"]).toBe(ORGANIZATION_ID);
    expect(node.sameAs).toEqual(["https://reseller.yupay.uz", "https://partners.yupay.uz"]);
  });

  it("website carries the given site", () => {
    expect(website("https://reseller.yupay.uz")).toMatchObject({
      "@type": "WebSite",
      url: "https://reseller.yupay.uz",
    });
  });

  it("service refers back to the organization by @id, not by copy", () => {
    const node = service("https://reseller.yupay.uz", "YuPay Wholesale");
    expect(node.provider).toEqual({ "@id": ORGANIZATION_ID });
    expect(node.areaServed).toEqual(["UZ", "RU", "KZ"]);
  });

  it("service takes its name from the caller rather than hardcoding one locale", () => {
    expect(service("https://reseller.yupay.uz", "YuPay Оптом").name).toBe("YuPay Оптом");
    expect(service("https://reseller.yupay.uz", "YuPay Optom").name).toBe("YuPay Optom");
  });

  it("faqPage turns q/a pairs into Question/Answer nodes", () => {
    const node = faqPage([
      { q: "Q1", a: "A1" },
      { q: "Q2", a: "A2" },
    ]);
    expect(node["@type"]).toBe("FAQPage");
    expect(node.mainEntity).toEqual([
      { "@type": "Question", name: "Q1", acceptedAnswer: { "@type": "Answer", text: "A1" } },
      { "@type": "Question", name: "Q2", acceptedAnswer: { "@type": "Answer", text: "A2" } },
    ]);
  });

  it("breadcrumbs numbers positions from 1", () => {
    const node = breadcrumbs([
      { name: "Docs", url: "https://reseller.yupay.uz/docs" },
      { name: "Quickstart", url: "https://reseller.yupay.uz/docs/quickstart" },
    ]);
    expect(node.itemListElement).toEqual([
      { "@type": "ListItem", position: 1, name: "Docs", item: "https://reseller.yupay.uz/docs" },
      {
        "@type": "ListItem",
        position: 2,
        name: "Quickstart",
        item: "https://reseller.yupay.uz/docs/quickstart",
      },
    ]);
  });

  it("techArticle omits description when absent", () => {
    const withDesc = techArticle({
      headline: "Первый заказ",
      description: "lead",
      url: "https://reseller.yupay.uz/docs/quickstart",
      dateModified: "2026-09-17T00:00:00.000Z",
    });
    expect(withDesc.description).toBe("lead");

    const withoutDesc = techArticle({
      headline: "Первый заказ",
      url: "https://reseller.yupay.uz/docs/quickstart",
      dateModified: "2026-09-17T00:00:00.000Z",
    });
    expect(withoutDesc).not.toHaveProperty("description");
    expect(withoutDesc).not.toHaveProperty("about");
    expect(withoutDesc["@type"]).toBe("TechArticle");
  });

  it("techArticle carries `about` when the page has a subject", () => {
    const node = techArticle({
      headline: "API",
      about: "Game top-up API",
      url: "https://reseller.yupay.uz/api",
      dateModified: "2026-09-17T00:00:00.000Z",
    });
    expect(node.about).toBe("Game top-up API");
  });
});
