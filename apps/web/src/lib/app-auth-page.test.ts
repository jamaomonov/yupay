import { runInNewContext } from "node:vm";

import { describe, expect, it } from "vitest";

import { appAuthScript } from "./app-auth-page";

const SCRIPT = appAuthScript({
  googleClientId: "gid.apps.googleusercontent.com",
  telegramBotId: "8702808191",
  text: { ru: { wait: "ждём", failed: "ошибка" }, en: { wait: "wait", failed: "failed" } },
});

function state(to: string, l = "ru"): string {
  return btoa(JSON.stringify({ to, n: "nonce", l }))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/** Runs the page's script at `href`; returns where it sent the browser and what it said. */
function run(href: string): { went: string | null; text: string; address: string } {
  const url = new URL(href);
  const out = { went: null as string | null, text: "", address: href };
  const location = {
    origin: url.origin,
    search: url.search,
    hash: url.hash,
    replace: (to: string) => {
      out.went = to;
    },
  };
  const node = {
    set textContent(value: string) {
      out.text = value;
    },
  };
  runInNewContext(SCRIPT, {
    location,
    history: {
      replaceState: (_: unknown, __: string, next: string) => {
        out.address = next;
      },
    },
    document: { getElementById: () => node },
    URL,
    URLSearchParams,
    atob,
    btoa,
  });
  return out;
}

describe("app-auth bounce page", () => {
  const app = "yupay://auth";

  it("starts Google with our redirect and the app's state", () => {
    const s = state(app);
    const { went } = run(`https://yupay.uz/app-auth?provider=google&state=${s}`);
    const google = new URL(went ?? "");
    expect(google.origin).toBe("https://accounts.google.com");
    expect(google.searchParams.get("redirect_uri")).toBe("https://yupay.uz/app-auth");
    expect(google.searchParams.get("response_type")).toBe("token");
    expect(google.searchParams.get("state")).toBe(s);
  });

  it("starts Telegram with the bot and a return to this page", () => {
    const s = state(app);
    const { went } = run(`https://yupay.uz/app-auth?provider=telegram&state=${s}`);
    const tg = new URL(went ?? "");
    expect(tg.origin).toBe("https://oauth.telegram.org");
    expect(tg.searchParams.get("bot_id")).toBe("8702808191");
    expect(tg.searchParams.get("return_to")).toBe(
      `https://yupay.uz/app-auth?provider=telegram&state=${s}`,
    );
  });

  it("hands the Google token to the app and clears it from the address", () => {
    const s = state(app);
    const out = run(`https://yupay.uz/app-auth#access_token=tok123&state=${s}`);
    const back = new URL(out.went ?? "");
    expect(back.protocol).toBe("yupay:");
    expect(back.searchParams.get("access_token")).toBe("tok123");
    expect(back.searchParams.get("state")).toBe(s);
    expect(out.address).toBe("https://yupay.uz/app-auth");
  });

  it("hands the Telegram payload to the app", () => {
    const s = state("exp://192.168.1.20:8081/--/auth");
    const out = run(
      `https://yupay.uz/app-auth?provider=telegram&state=${s}#tgAuthResult=eyJpZCI6MX0`,
    );
    expect(out.went).toContain("exp://192.168.1.20:8081/--/auth?provider=telegram&tg=eyJpZCI6MX0");
  });

  it.each([
    "https://evil.example/collect",
    "exp://evil.example:8081/--/auth",
    "exp://8.8.8.8:8081/--/auth",
    "exp://10.attacker.example:8081/--/auth",
    "exp://192.168.evil.example/--/auth",
    "exp://172.16.0.1.evil.example/--/auth",
    "exp://10.0.0.300:8081/--/auth",
    "javascript:alert(1)",
  ])("never sends a credential to %s", (to) => {
    const out = run(`https://yupay.uz/app-auth#access_token=tok123&state=${state(to)}`);
    expect(out.went).toBeNull();
    expect(out.text).toBe("ошибка");
  });

  it("starts Steam with this page as the OpenID return address", () => {
    const s = state(app);
    const { went } = run(`https://yupay.uz/app-auth?provider=steam&state=${s}`);
    const steam = new URL(went ?? "");
    expect(steam.origin + steam.pathname).toBe("https://steamcommunity.com/openid/login");
    expect(steam.searchParams.get("openid.realm")).toBe("https://yupay.uz");
    expect(steam.searchParams.get("openid.return_to")).toBe(
      `https://yupay.uz/app-auth?provider=steam&state=${s}`,
    );
  });

  it("hands Steam's whole openid set to the app and clears it from the address", () => {
    const s = state(app);
    const out = run(
      `https://yupay.uz/app-auth?provider=steam&state=${s}&openid.mode=id_res` +
        "&openid.claimed_id=https%3A%2F%2Fsteamcommunity.com%2Fopenid%2Fid%2F7656&openid.sig=x%2By",
    );
    const back = new URL(out.went ?? "");
    expect(back.protocol).toBe("yupay:");
    expect(back.searchParams.get("provider")).toBe("steam");
    expect(back.searchParams.get("state")).toBe(s);
    const raw = (back.searchParams.get("steam") ?? "").replace(/-/g, "+").replace(/_/g, "/");
    expect(JSON.parse(atob(raw))).toEqual({
      "openid.mode": "id_res",
      "openid.claimed_id": "https://steamcommunity.com/openid/id/7656",
      "openid.sig": "x+y",
    });
    expect(out.address).toBe("https://yupay.uz/app-auth");
  });

  it("reports a cancelled Steam sign-in as an error", () => {
    const s = state(app);
    const back = new URL(
      run(`https://yupay.uz/app-auth?provider=steam&state=${s}&openid.mode=cancel`).went ?? "",
    );
    expect(back.searchParams.get("error")).toBe("1");
  });

  it("refuses a missing or broken state", () => {
    expect(run("https://yupay.uz/app-auth?provider=google").went).toBeNull();
    expect(run("https://yupay.uz/app-auth?provider=google&state=%%%").went).toBeNull();
  });

  it("speaks the app's language", () => {
    const out = run(`https://yupay.uz/app-auth?provider=nope&state=${state(app, "en")}`);
    expect(out.text).toBe("failed");
  });
});
