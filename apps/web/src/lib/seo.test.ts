import { expect, test } from "vitest";

import { truncate } from "./seo";

test("truncate leaves short strings untouched", () => {
  expect(truncate("Короткое описание")).toBe("Короткое описание");
});

test("truncate cuts long strings to <= max at a word boundary with an ellipsis", () => {
  const long =
    "Пополнение Steam в Узбекистане за сумы без комиссии: сколько платите — столько и зачисляется на кошелёк Steam, один к одному. Оплата картами Uzcard и Humo через Click, Payme или Uzum, моментально.";
  const out = truncate(long, 155);
  expect(out.length).toBeLessThanOrEqual(156); // 155 + the ellipsis char
  expect(out.endsWith("…")).toBe(true);
  expect(out).not.toMatch(/[\s,]…$/); // no dangling space/comma before the ellipsis
  expect(long.startsWith(out.slice(0, -1))).toBe(true); // prefix of the original
});
