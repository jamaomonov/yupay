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

| Table | Owned by |
|---|---|
| `auth_sessions` | this module |
| `users`, `telegram_links` | the `users` module (this module is the primary writer) |

## Token model

See [ADR-0007](../../../../../docs/decisions/0007-jwt-format-and-rotation.md) for the
full spec. Summary:

| Kind | TTL | Storage | Use |
|---|---|---|---|
| `access` | 15 min | stateless JWT | `Authorization: Bearer <access>` |
| `refresh` | 30 days | hash in `auth_sessions`, plaintext to client | `POST /auth/refresh` |
| `guest` | 30 min | session row in `auth_sessions(kind='guest')` | `Authorization: Guest <jwt>` |
| `ws` | 60 s | stateless JWT | WebSocket `Upgrade` query string |

## HTTP surface

| Method | Path | Body | Returns |
|---|---|---|---|
| `POST` | `/api/v1/auth/telegram/webapp` | `{init_data}` | `TokensOut` |
| `POST` | `/api/v1/auth/telegram/widget` | Login Widget JSON | `TokensOut` |
| `POST` | `/api/v1/auth/guest` | `{email}` | `GuestTokenOut` |
| `POST` | `/api/v1/auth/refresh` | `{refresh_token}` | `TokensOut` |
| `POST` | `/api/v1/auth/logout` | `{refresh_token}` | `204 No Content` |
| `GET` | `/api/v1/auth/me` | — (Bearer) | `MeOut` |

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

## What's deliberately **not** here yet

- **Redis access-token revocation blocklist** (`auth:revoked:{jti}`). Refresh rotation +
  short access TTL is enough at MVP; we'll add it when the first need arises (suspected
  theft, admin force-logout).
- **Email verification for guest checkout.** Per ADR-0007, guest tokens are issued
  unverified — the downstream `orders` module is responsible for sending the receipt and
  voucher to the supplied address.
- **Service-to-service tokens.** Reserved for the microservice split (post-MVP).
