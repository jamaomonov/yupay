/**
 * The page the mobile app opens to sign in with Google, Telegram or Steam (ADR-0101).
 *
 * The app cannot run either provider's web flow inside itself, and neither provider will
 * redirect to an app scheme, so the app opens `https://yupay.uz/app-auth` in the system
 * browser. This page sends the buyer to the provider, receives the answer in the URL
 * fragment (Steam: in the query), and passes it to the app's own URL (`yupay://…`, or
 * `exp://<LAN IP>` from Expo Go in development). The app then posts it to `/auth/google`,
 * `/auth/telegram/widget` or `/auth/steam`. Steam's `openid.return_to` is this page, which the
 * API accepts as one of its two Steam return addresses (`auth.service._steam_return_prefix`).
 *
 * It is a bare HTML document served by a route handler, outside the `[locale]` layout, on
 * purpose: that layout loads Yandex.Metrika and Google Tag Manager, which report the full
 * URL, and here the fragment carries a Google access token or a signed Telegram payload.
 * The fragment never reaches a server.
 *
 * `state` is base64url JSON `{to, n, l}` minted by the app: where to return, a nonce the app
 * checks on the way back, the language. A `to` outside the allowlist is refused, so the page
 * cannot be used to hand a credential to some other address.
 */

export interface AppAuthConfig {
  googleClientId: string;
  telegramBotId: string;
  /** Shown while redirecting and when the page cannot continue, per locale. */
  text: Record<string, { wait: string; failed: string }>;
}

/** JSON safe to drop inside a `<script>`. */
function inline(value: unknown): string {
  return JSON.stringify(value).replace(/</g, "\\u003c");
}

/** The page's script; exported so the tests can run it against a fake `location`. */
export function appAuthScript(config: AppAuthConfig): string {
  return `(function () {
  var GOOGLE = ${inline(config.googleClientId)};
  var TG_BOT = ${inline(config.telegramBotId)};
  var TEXT = ${inline(config.text)};
  var SELF = location.origin + "/app-auth";
  // A whole dotted quad, checked by number. A prefix pattern let
  // "10.attacker.example" through as if it were a LAN address.
  function privateIp(host) {
    var m = /^(\\d{1,3})\\.(\\d{1,3})\\.(\\d{1,3})\\.(\\d{1,3})$/.exec(host);
    if (!m) return false;
    var o = [+m[1], +m[2], +m[3], +m[4]];
    for (var i = 0; i < 4; i++) if (o[i] > 255) return false;
    return o[0] === 10 || o[0] === 127 ||
      (o[0] === 192 && o[1] === 168) ||
      (o[0] === 172 && o[1] >= 16 && o[1] <= 31);
  }

  function allowed(to) {
    var u;
    try { u = new URL(to); } catch (e) { return false; }
    if (u.protocol === "yupay:") return true;
    return u.protocol === "exp:" && privateIp(u.hostname);
  }
  function decode(state) {
    try {
      var j = JSON.parse(atob(state.replace(/-/g, "+").replace(/_/g, "/")));
      return j && typeof j.to === "string" && allowed(j.to) ? j : null;
    } catch (e) { return null; }
  }
  function say(key, st) {
    var t = TEXT[(st && st.l) || "ru"] || TEXT.ru;
    document.getElementById("m").textContent = t[key];
  }

  var query = new URLSearchParams(location.search);
  var hash = new URLSearchParams(location.hash.slice(1));
  var state = hash.get("state") || query.get("state") || "";
  var st = decode(state);
  if (!st) { say("failed", null); return; }
  say("wait", st);

  function back(params) {
    params.set("state", state);
    // Drop the credential from this page's address before leaving it.
    history.replaceState(null, "", SELF);
    location.replace(st.to + (st.to.indexOf("?") === -1 ? "?" : "&") + params.toString());
  }

  if (query.get("openid.mode") === "id_res") {
    // Steam's OpenID answer arrives in the query, not the fragment. The whole openid.* set
    // goes back: the API hands it to Steam for the check (ADR-0101).
    var steam = {};
    query.forEach(function (v, k) { if (k.indexOf("openid.") === 0) steam[k] = v; });
    back(new URLSearchParams({
      provider: "steam",
      steam: btoa(JSON.stringify(steam)).replace(/\\+/g, "-").replace(/\\//g, "_").replace(/=+$/, "")
    }));
  } else if (query.get("openid.mode")) {
    back(new URLSearchParams({ error: "1" }));
  } else if (hash.get("access_token")) {
    back(new URLSearchParams({ provider: "google", access_token: hash.get("access_token") }));
  } else if (hash.get("tgAuthResult")) {
    back(new URLSearchParams({ provider: "telegram", tg: hash.get("tgAuthResult") }));
  } else if (hash.get("error") || query.get("error")) {
    back(new URLSearchParams({ error: "1" }));
  } else if (query.get("provider") === "google" && GOOGLE) {
    location.replace("https://accounts.google.com/o/oauth2/v2/auth?" + new URLSearchParams({
      client_id: GOOGLE, redirect_uri: SELF, response_type: "token",
      scope: "openid email profile", state: state, prompt: "select_account"
    }).toString());
  } else if (query.get("provider") === "telegram" && TG_BOT) {
    location.replace("https://oauth.telegram.org/auth?" + new URLSearchParams({
      bot_id: TG_BOT, origin: location.origin, request_access: "write",
      return_to: SELF + "?" + new URLSearchParams({ provider: "telegram", state: state }).toString()
    }).toString());
  } else if (query.get("provider") === "steam") {
    location.replace("https://steamcommunity.com/openid/login?" + new URLSearchParams({
      "openid.ns": "http://specs.openid.net/auth/2.0",
      "openid.mode": "checkid_setup",
      "openid.return_to": SELF + "?" + new URLSearchParams({ provider: "steam", state: state }).toString(),
      "openid.realm": location.origin,
      "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
      "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select"
    }).toString());
  } else {
    say("failed", st);
  }
})();`;
}

export function appAuthHtml(config: AppAuthConfig): string {
  return `<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta name="referrer" content="no-referrer">
<title>YuPay</title>
<style>
  html, body { margin: 0; height: 100%; background: #060712; color: #9da8c8;
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  main { min-height: 100%; display: flex; align-items: center; justify-content: center;
    padding: 0 24px; text-align: center; box-sizing: border-box; }
</style>
</head>
<body>
<main><p id="m"></p></main>
<script>${appAuthScript(config)}</script>
</body>
</html>`;
}
