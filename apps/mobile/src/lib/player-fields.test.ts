import { describe, expect, it } from "vitest";

import { parseSaved } from "./player-fields";

describe("parseSaved", () => {
  it("keeps trimmed strings and drops everything else", () => {
    expect(parseSaved('{"player_id":" 512 ","server_id":"","x":5}')).toEqual({ player_id: "512" });
  });

  it("reads nothing from nothing or from garbage", () => {
    expect(parseSaved(null)).toEqual({});
    expect(parseSaved("not json")).toEqual({});
    expect(parseSaved("[1,2]")).toEqual({});
  });
});
