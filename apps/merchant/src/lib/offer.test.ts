import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { parseOffer } from "./offer";

const SOURCE = readFileSync(
  join(process.cwd(), "..", "..", "docs", "legal", "merchant-offer.ru.md"),
  "utf8",
);

describe("the public offer", () => {
  const { revision, blocks } = parseOffer(SOURCE);
  const text = blocks.map((b) => b.text).join("\n");

  it("names a dated revision", () => {
    expect(revision).toMatch(/^\d{2}\.\d{2}\.\d{4}$/);
  });

  it("is final: no draft marker and no unresolved placeholder", () => {
    expect(text).not.toMatch(/черновик|draft|на утверждение/i);
  });

  it("says «Реселлер», never «Партнёр» — the owner's word for this program", () => {
    expect(text).toMatch(/Реселлер/);
    expect(text).not.toMatch(/партн[её]р/i);
  });

  it("keeps the HTML comment and the H1 out of the rendered blocks", () => {
    expect(text).not.toContain("<!--");
    expect(text).not.toContain("merchant_users.offer_version");
    expect(blocks[0]?.heading).toBe(true);
  });

  it("splits sections into headings and joins wrapped lines into paragraphs", () => {
    expect(blocks.filter((b) => b.heading).length).toBeGreaterThanOrEqual(10);
    expect(blocks.every((b) => !b.text.includes("\n"))).toBe(true);
    expect(text).not.toContain("**");
  });

  it("refuses a document without a revision line", () => {
    expect(() => parseOffer("# Оферта\n\n## 1. Предмет\n\nТекст.")).toThrow();
  });
});
