# The Telegram bridge the mini app serves itself

`apps/miniapp/public/js/telegram-web-app.js` is a pinned copy of
`https://telegram.org/js/telegram-web-app.js`. The mini app loads **ours**, not
Telegram's, and that is deliberate.

## Why we host it

It used to be a plain blocking `<script>` pointing at `telegram.org`. Some
Uzbek carriers drop that domain — the Telegram _app_ keeps working, because it
talks to its own data centres rather than to the website — and a blocking
script in `<head>` that never answers stops the parser before `<body>` exists.

Measured on 2026-09-17 against the live site with only `telegram.org` dropped:

|                       |                                         |
| --------------------- | --------------------------------------- |
| our HTML arrived      | 184 ms                                  |
| painted               | nothing, for the full 25 s of the probe |
| `document.readyState` | still `loading`                         |

Inside Telegram that is «Не удалось загрузить YuPay» — the error users
reported, with the server idle and healthy the whole time. Reported as "the
site opens in my browser but the mini app doesn't", which is exactly what the
split looks like: our domain was reachable, Telegram's was not.

Two things changed: the bridge now comes from our origin with `defer`, and
`index.html` carries a boot screen so the page paints without waiting for the
bundle. `apps/miniapp/src/index-html.test.ts` fails if either is undone, or if
any third-party `<script src>` reappears in that file.

## Refreshing the copy

The API this app uses (`initData`, `expand`, `BackButton`, `MainButton`,
themes, `openLink`) has been stable for years, so the copy ages slowly. Refresh
it when Telegram ships a Bot API version whose mini-app features we want:

```bash
curl -fsS -o apps/miniapp/public/js/telegram-web-app.js \
  https://telegram.org/js/telegram-web-app.js
pnpm --filter @yupay/miniapp exec vitest run src/index-html.test.ts
```

Then open the mini app in a real Telegram client — the bridge is the one thing
no test here can exercise, because it needs the host app on the other side of
the `postMessage` channel. Check that the page renders, the back button works,
and an order can be placed; then deploy as usual.

Do **not** "fix" a stale copy by pointing the tag back at `telegram.org`: that
reintroduces the outage above for exactly the users who reported it.

## If the mini app fails to load again

1. Is it us? `curl -s -o /dev/null -w "%{http_code}" https://app.yupay.uz/` and
   the container: `docker compose -f docker-compose.prod.yml ps miniapp`.
2. Does the boot screen appear (spinner, «Загружаем…»)? Then the HTML is
   arriving and the bundle or the API is the problem — check
   `docker compose logs --since 1h caddy | grep app.yupay.uz` for status codes
   and durations.
3. Blank page with Telegram's own error and no request in our logs? Something
   between the device and us: ask the user whether `https://yupay.uz` opens in
   their browser (same edge, same path — if it does, the network is fine) and
   check Cloudflare → Security → Events filtered by country.
4. A user on a very slow link (the first report showed 0,5 КБ/с) will now see
   the boot screen and a retry button rather than an error; the critical path
   is still ~220 KB, which needs roughly 25 KB/s to open in under ten seconds.
