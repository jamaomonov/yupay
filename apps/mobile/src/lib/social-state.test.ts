import { describe, expect, it } from "vitest";

import { decodeBase64Utf8, encodeState, readResult } from "./social-state";

describe("social sign-in state", () => {
  it("encodes a url-safe state the page can read back", () => {
    const state = encodeState("yupay://auth", "n1", "uz");
    expect(state).not.toMatch(/[+/=]/);
    expect(JSON.parse(decodeBase64Utf8(state))).toEqual({ to: "yupay://auth", n: "n1", l: "uz" });
  });

  it("decodes a Cyrillic Telegram name", () => {
    const payload = Buffer.from(JSON.stringify({ first_name: "Жамшид" })).toString("base64");
    expect(JSON.parse(decodeBase64Utf8(payload))).toEqual({ first_name: "Жамшид" });
  });

  it("reads a Google token and a Telegram payload", () => {
    expect(readResult({ state: "s", provider: "google", access_token: "t" }, "s")).toEqual({
      provider: "google",
      accessToken: "t",
    });
    const tg = Buffer.from(JSON.stringify({ id: 1, hash: "h" })).toString("base64");
    expect(readResult({ state: "s", provider: "telegram", tg }, "s")).toEqual({
      provider: "telegram",
      payload: { id: 1, hash: "h" },
    });
  });

  it("reads Steam's openid set and refuses a mangled one", () => {
    const set = {
      "openid.mode": "id_res",
      "openid.claimed_id": "https://steamcommunity.com/openid/id/7",
    };
    const steam = Buffer.from(JSON.stringify(set)).toString("base64url");
    expect(readResult({ state: "s", provider: "steam", steam }, "s")).toEqual({
      provider: "steam",
      params: set,
    });
    const foreign = Buffer.from(JSON.stringify({ "openid.mode": "id_res", x: "1" })).toString(
      "base64url",
    );
    expect(readResult({ state: "s", provider: "steam", steam: foreign }, "s")).toEqual({
      error: true,
    });
  });

  it("drops an answer for another attempt, an error, or a declined prompt", () => {
    expect(readResult({ state: "other", provider: "google", access_token: "t" }, "s")).toEqual({
      error: true,
    });
    expect(readResult({ state: "s", error: "1" }, "s")).toEqual({ error: true });
    const declined = Buffer.from("false").toString("base64");
    expect(readResult({ state: "s", provider: "telegram", tg: declined }, "s")).toEqual({
      error: true,
    });
  });
});
