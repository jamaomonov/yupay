import { expect, it } from "vitest";

import { prefillFromQuery } from "./purchase-prefill";

import type { FormField } from "./catalog";

const LOGIN: FormField = {
  key: "steam_login",
  label: { ru: "Логин Steam", en: "Steam login", uz: "Steam login" },
  type: "text",
  required: true,
  pattern: "^[A-Za-z0-9_-]{3,64}$",
};

it("takes a field named in the URL and a dollar amount", () => {
  const q = new URLSearchParams("steam_login=gaben_42&amount=10");
  expect(prefillFromQuery(q, [LOGIN])).toEqual({
    fields: { steam_login: "gaben_42" },
    amount: "10",
  });
});

it("drops a value its field's pattern refuses, and an amount that is not a number", () => {
  const q = new URLSearchParams("steam_login=a b&amount=10$");
  expect(prefillFromQuery(q, [LOGIN])).toEqual({ fields: {}, amount: null });
});

it("ignores parameters that are not the product's fields", () => {
  const q = new URLSearchParams("email=x@y.z&utm_source=home");
  expect(prefillFromQuery(q, [LOGIN])).toEqual({ fields: {}, amount: null });
});
