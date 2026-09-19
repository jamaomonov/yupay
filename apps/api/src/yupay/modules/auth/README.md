# `auth` module

Authentication and session management for YuPay.

## Responsibilities

- Verify Telegram `initData` (Mini App) and Login Widget payloads.
- Mint and rotate JWT access + opaque refresh tokens (EdDSA / Ed25519).
- Mint short-lived guest checkout tokens bound to an email hash.
- Resolve the current user from a Bearer token (FastAPI dependency).

## Public interface

Cross-module callers must import only from
[`yupay.modules.auth.api`](./api.py) — never from `routes`, `service`, or `models`:

```python
from yupay.modules.auth.api import (
    current_user,               # FastAPI dep (Bearer JWT)
    telegram_init_data_login,   # service func
    telegram_widget_login,
    guest_checkout,
    refresh_session,
    logout,
    SessionTokens,              # dataclass
    GuestToken,
    router,                     # FastAPI router mounted at /api/v1/auth
)
```

## Tables owned

| Table                     | Owned by                                               |
| ------------------------- | ------------------------------------------------------ |
| `auth_sessions`           | this module                                            |
| `users`, `telegram_links` | the `users` module (this module is the primary writer) |

## Token model

See [ADR-0007](../../../../../docs/decisions/0007-jwt-format-and-rotation.md) for the
full spec. Summary:

| Kind          | TTL     | Storage                                      | Use                                                                                                                                                                                                  |
| ------------- | ------- | -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `access`      | 15 min  | stateless JWT                                | `Authorization: Bearer <access>`                                                                                                                                                                     |
| `refresh`     | 30 days | hash in `auth_sessions`, plaintext to client | `POST /auth/refresh`                                                                                                                                                                                 |
| `guest`       | 30 min  | session row in `auth_sessions(kind='guest')` | `Authorization: Guest <jwt>` — order status/reviews. Freely mintable from an email; **does NOT unlock delivered codes.**                                                                             |
| `guest_order` | 7 days  | stateless JWT (carries `order_id`)           | `Authorization: Guest <jwt>` for `GET /orders/{id}/deliveries` — order-scoped magic link in the delivered email. See [ADR-0042](../../../../../docs/decisions/0042-guest-code-access-magic-link.md). |
| `ws`          | 60 s    | stateless JWT                                | WebSocket `Upgrade` query string                                                                                                                                                                     |

## HTTP surface

| Method | Path                           | Body              | Returns          |
| ------ | ------------------------------ | ----------------- | ---------------- |
| `POST` | `/api/v1/auth/telegram/webapp` | `{init_data}`     | `TokensOut`      |
| `POST` | `/api/v1/auth/telegram/widget` | Login Widget JSON | `TokensOut`      |
| `POST` | `/api/v1/auth/guest`           | `{email}`         | `GuestTokenOut`  |
| `POST` | `/api/v1/auth/refresh`         | `{refresh_token}` | `TokensOut`      |
| `POST` | `/api/v1/auth/logout`          | `{refresh_token}` | `204 No Content` |
| `GET`  | `/api/v1/auth/me`              | — (Bearer)        | `MeOut`          |

## Sequence diagrams

- [`docs/architecture/sequence-diagrams/auth-telegram-webapp.mmd`](../../../../../docs/architecture/sequence-diagrams/auth-telegram-webapp.mmd)
- [`docs/architecture/sequence-diagrams/auth-telegram-widget.mmd`](../../../../../docs/architecture/sequence-diagrams/auth-telegram-widget.mmd)
- [`docs/architecture/sequence-diagrams/auth-guest.mmd`](../../../../../docs/architecture/sequence-diagrams/auth-guest.mmd)
- [`docs/architecture/sequence-diagrams/auth-refresh.mmd`](../../../../../docs/architecture/sequence-diagrams/auth-refresh.mmd)

## Tests

- `apps/api/tests/unit/test_jwt.py` — JWT mint/verify happy & sad paths.
- `apps/api/tests/unit/test_telegram.py` — HMAC for `initData` and Login Widget.
- `apps/api/tests/integration/test_auth_routes.py` — full HTTP flow against a real
  Postgres (testcontainers).

## Revocation

- **Access-token blocklist (`auth:revoked:{jti}`).** Set on explicit `logout` when the
  request carries the access token, so it stops working immediately.
- **Session blocklist (`auth:revoked_sid:{sid}`).** Set on every session-revocation path
  (refresh rotation, `logout`, reuse-detection, password-reset revoke-all); `current_user`
  checks it so a revoked session's still-valid access tokens die at once instead of
  lingering up to 15 min. TTL = the access-token lifetime.

## What's deliberately **not** here yet

- **Full email verification for guest _checkout_.** Guest tokens are issued unverified at
  checkout (the receipt/voucher goes to the supplied address). Delivered **codes** are
  gated behind an order-scoped magic link — see [ADR-0042](../../../../../docs/decisions/0042-guest-code-access-magic-link.md).
- **Service-to-service tokens.** Reserved for the microservice split (post-MVP).

## Google Sign-In

`POST /auth/google` принимает GIS credential (JWT, подписанный Google) с
официальной кнопки на вебе, проверяет подпись и audience
(`GOOGLE_OAUTH_CLIENT_ID`) через google-auth и линкует по **верифицированному**
email: существующий аккаунт с этим адресом получает сессию, нового
пользователя создаём с `email_verified_at = now()`.

Два правила безопасности (пины в `test_auth_google.py`):

- неверифицированный Google-email никогда не открывает сессию;
- Google-вход в аккаунт с неверифицированным email обнуляет посаженный там
  пароль: парольный логин такие аккаунты не пускает, значит хэш мог посадить
  только тот, кто адресом не владеет — пометить email верифицированным, не
  сняв пароль, значило бы вооружить чужой пароль.

**Аватар и имя идут через `users.identity_guard`.** Sentry, продакшн: реальный
Google avatar URL длиннее 1024 символов уронил `INSERT INTO users`
(`StringDataRightTruncationError`) — регистрация не проходила вовсе.
`users.photo_url` теперь `text` (миграция 0083), но `identity.picture` /
`identity.name` всё равно идут через `safe_avatar_url`/`safe_display_name`
(не напрямую в `User(...)`), а не только полагаются на ширину колонки — см.
`users`'s README, раздел "Identity-field guards".

**Конкурентная первая регистрация — SAVEPOINT, не 500.** Sentry, продакшн,
2026-09-18 (Telegram-путь, но форма та же): два запроса на один и тот же ещё
не существующий email/tg_user_id/steam_id гоняют одно и то же
SELECT-then-INSERT — оба видят "не найден", оба пытаются вставить.
Проигравший раньше падал в 500 (`asyncpg.UniqueViolationError` на
уникальном индексе). Теперь INSERT идёт внутри `db.begin_nested()`
(`session.begin_nested()` в `users.service`); на `IntegrityError` savepoint
откатывает только эту половинную вставку, а код перечитывает уже
закоммиченную строку победителя и продолжает так, как будто нашёл её с
самого начала — та же ветка, что для уже существующего аккаунта. Тот же
паттерн в `users.service.upsert_user_by_telegram`/`upsert_user_by_steam`
(уникальность на `tg_user_id`/`steam_id`). См. `test_auth_google.py` и
`test_users_upsert_race.py` — оба гоняют настоящую гонку двумя параллельными
сессиями, а не последовательные вызовы.

## Steam Sign-In

Steam так и не завёл OAuth — только OpenID 2.0. `GET /auth/steam/start`
уводит браузер на steamcommunity.com; Steam возвращает на веб-страницу
`/auth/steam/callback` с подписанными `openid.*`-параметрами, страница
отдаёт их в `POST /auth/steam`, а бэкенд перепроверяет весь набор у самого
Steam (`check_authentication`) — единственный доверенный способ; заодно
Steam сам гасит повторное использование assertion. Email Steam не отдаёт:
аккаунт создаётся/находится по steamid64 через `steam_links` — полный
аналог Telegram-входа. `return_to`, указывающий не на наш колбек,
отклоняется до любого сетевого вызова.

**Ключ Steam Web API — общий.** `fetch_persona` (ник и аватар после входа)
тратит ту же дневную квоту в 100k вызовов, что и предпокупочная проверка
получателя в `gifts.profile`. Поэтому каждый такой вызов считается в
`yupay_steam_web_api_calls_total{consumer="auth_signin"}`: потолок применяется
к сумме по `consumer`, а разбивка показывает, кто именно её тратит. Сам
OpenID-запрос `check_authentication` ключа не несёт и квоту не тратит —
поэтому не считается. `resolve_persona` требует `consumer` явным аргументом:
значение по умолчанию позволило бы новому вызову спрятаться в чужих цифрах.
См. `docs/architecture/metrics.md` и
`docs/runbooks/steam-web-api-quota.md`.
