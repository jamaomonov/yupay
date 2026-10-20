# 0101. The mobile app carries its refresh token in the body

- **Status**: Accepted
- **Date**: 2026-10-19
- **Deciders**: @jamaomonov
- **Tags**: backend | security | frontend

## Context and problem statement

A session is a 15-minute access JWT plus a 30-day rotating refresh token. Every surface so far
is a browser, so the refresh token rides an `HttpOnly` cookie on the API's domain and never
appears in JSON, which keeps it out of reach of script on the page.

The mobile app (ADR-0100) is not a browser. React Native's `fetch` does keep cookies, but in a
platform cookie store the app does not control: it cannot be put in the device keychain,
inspected, or cleared on sign-out with any certainty. The app needs the refresh token as a
value it stores in `expo-secure-store`.

## Decision drivers

- No change in what the website, the mini app and the admin send or receive.
- Script running on the website must not be able to read a refresh token, before or after.
- One session model on the server: same rotation, reuse detection and revocation.

## Considered options

1. **Rely on the native cookie store.** Nothing changes on the server; the token sits where the
   app cannot reach it, and a logout that fails to clear it leaves a live session behind.
2. **A body mode the client asks for.** Sign-in routes return the refresh token in the body
   when the request says `X-Yupay-Token-Transport: body`; refresh and logout accept it in the
   body.
3. **A separate mobile auth module.** A second token family for one client; duplicated rotation
   and revocation logic.

## Decision outcome

**Chosen option:** 2, because it reuses the session model and its tests, and the browser path
is untouched.

The rule that keeps it safe: **a body token is only ever issued against a credential the caller
presents in the request** — a password, a Google token, a Steam assertion, or the refresh token
itself in the body. A cookie is never answered with a body token, so script on the website,
which can make credentialed requests but cannot read the cookie, cannot turn its session into a
readable token by adding the header. `POST /auth/refresh` with a body rotates the body token and
sets no cookie; without a body (or with `{}`, which the mini app's logout sends) it behaves as
before.

`TokensOut` gains optional `refresh_token` and `refresh_expires_in`; every route excludes `None`
fields, so a browser's JSON is unchanged.

### Google and Telegram in the app: the `/app-auth` bounce

Neither provider redirects to an app scheme, and the web flows (Google's token client,
Telegram's Login Widget) need a page on our domain. The app opens
`https://yupay.uz/app-auth?provider=…&state=…` in the system browser
(`WebBrowser.openAuthSessionAsync`). That page sends the buyer to Google (implicit flow,
`redirect_uri=https://yupay.uz/app-auth`) or to `oauth.telegram.org` (`return_to` back to the
page), receives the answer in the URL fragment, and passes it to the app's URL in `state`. The
app checks `state` is the one it sent and posts the Google access token to `/auth/google` or
the decoded Telegram payload to `/auth/telegram/widget`, both with body transport.

- The page is a route handler outside the `[locale]` layout, so Yandex.Metrika and Google Tag
  Manager never load on it and never report a URL whose fragment holds a credential.
- It returns only to `yupay://…`, or to `exp://` on a private address (Expo Go during
  development). Anything else is refused, so the page cannot hand a credential elsewhere
  (`apps/web/src/lib/app-auth-page.test.ts`). "Private address" means a literal RFC 1918 or
  loopback IPv4, checked octet by octet: a first version matched by prefix and let
  `exp://10.attacker.example` through.
- Two residual risks are accepted for now. The `exp://` branch ships in production, so someone
  on the same Wi-Fi as a developer with Expo Go could pose as Metro. And `yupay://` is a plain
  custom scheme: on Android another app can register it and receive the credential. Before the
  first store release the return must move to a verified App Link / Universal Link (or a
  server-side one-time code), and the `exp://` branch should go.
- Google requires `https://yupay.uz/app-auth` among the web OAuth client's authorized redirect
  URIs. Telegram requires nothing new: the bot's domain is already `yupay.uz`.

### Positive consequences

- The app keeps its session in the device keychain and can drop it for certain.
- No new tables, keys or token types.

### Negative consequences

- The refresh token now exists in JSON on one path. A compromised device leaks a 30-day token;
  rotation with reuse detection still revokes the family on the next legitimate refresh.
- `/auth/telegram/widget` accepts the header too: the app signs in with the same signed,
  single-use payload the website's widget produces.

## Validation

`apps/api/tests/integration/test_auth_body_transport.py`: body mode on login, no cookie set; a
browser login still keeps the token out of JSON; body refresh rotates and the old token dies; a
cookie refresh with the header still answers without a token; body logout revokes; `{}` falls
back to the cookie.
