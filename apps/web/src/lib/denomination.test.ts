import { describe, expect, it } from "vitest";

import { displayDenomination } from "./denomination";

const NB = " ";

describe("displayDenomination", () => {
  it("keeps a parenthesised split on one line", () => {
    expect(displayDenomination("86 Diamonds (78 + 8)")).toBe(`86 Diamonds (78${NB}+${NB}8)`);
  });

  it("groups five-digit numbers and leaves four-digit ones", () => {
    expect(displayDenomination("10000 Robux")).toBe(`10${NB}000 Robux`);
    expect(displayDenomination("2500 Robux")).toBe("2500 Robux");
  });

  it("leaves a plain name alone", () => {
    expect(displayDenomination("50 + 5 Diamonds")).toBe("50 + 5 Diamonds");
  });
});
