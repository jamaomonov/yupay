import { describe, expect, it } from "vitest";

import { listStepsFromHtml } from "./blog-jsonld";

describe("listStepsFromHtml", () => {
  it("pulls li text out of the first ol", () => {
    expect(listStepsFromHtml("<p>intro</p><ol><li>One</li><li><strong>Two</strong></li></ol>")).toEqual(
      ["One", "Two"],
    );
  });

  it("returns empty when there is no list", () => {
    expect(listStepsFromHtml("<p>just prose</p>")).toEqual([]);
  });
});
