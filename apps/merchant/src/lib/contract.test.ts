import { describe, expect, it } from "vitest";

import { contract, endpoints } from "./contract";

/**
 * The "шесть эндпоинтов" ("six endpoints") claim is repeated as copy in
 * eighteen strings across the site and in /docs' hand-written intro table.
 * Nothing ties that number to the actual contract — a seventh endpoint
 * would make the copy wrong with no test failing. This pins it: a change to
 * `docs/api/merchant-openapi.json` that adds or removes a path fails here
 * first.
 */
describe("the merchant API surface", () => {
  it("has exactly six paths", () => {
    expect(Object.keys(contract().paths)).toHaveLength(6);
  });

  it("flattens to six endpoints, one operation per path", () => {
    expect(endpoints()).toHaveLength(6);
  });
});
