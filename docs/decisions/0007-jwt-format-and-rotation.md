# 0007. JWT format and rotation

- **Status**: Accepted
- **Date**: 2026-05-15
- **Deciders**: founding team
- **Tags**: backend, auth, security

## Context

YuPay authenticates three populations:

1. **Telegram users** — Mini App (via signed `initData`) and the public web (via Telegram
   Login Widget). Both produce a long-lived account in `users`.
2. **Guest checkout** — a user provides only an email; we accept the order without
   account creation. Tokens here are short-lived and scoped to a specific order.
3. **Service-to-service** — not in scope at MVP; reserved for the future microservice
   split.

We need a token format that:

- Survives a single-VPS deploy (statelessly verifiable) but supports **revocation** for the
  rare incidents that need it.
- Cannot be silently re-used after a logout.
- Carries a small, audit-friendly payload (no PII beyond the user id).
- Is portable across all three populations above.

## Decision

### Algorithm and keys

- **EdDSA (Ed25519)** via `pyjwt[crypto]`. Smaller and faster than RS256, no key-size
  decisions to make.
- Asymmetric: the private key lives only in the API container; the public key may be
  shared with any verifier (future microservices, edge gateways, BFFs).
- Keys rotate quarterly. Both keys are PEM-encoded and supplied via env vars
  (`JWT_PRIVATE_KEY`, `JWT_PUBLIC_KEY`). For dev, scripts/gen-secret.sh prints a fresh pair.

### Token kinds

| Kind           | TTL         | Refreshable             | Backed by `auth_sessions` row   | Used for                                                                   |
| -------------- | ----------- | ----------------------- | ------------------------------- | -------------------------------------------------------------------------- |
| `access`       | **15 min**  | no (rotate via refresh) | no (stateless)                  | Bearer auth header for normal user / guest requests                        |
| `refresh`      | **30 days** | yes (rotate-on-use)     | yes (hash stored, revocable)    | Mint a new access + new refresh                                            |
| `guest`        | **30 min**  | no                      | yes (audit only, no token hash) | Single-purpose checkout; not refreshable                                   |
| `ws-handshake` | **60 s**    | no                      | no                              | Authorise a WebSocket `upgrade` and bind the connection to a Redis channel |

### Claims

Common: `iss=yupay`, `iat`, `exp`, `jti`, `kid`.

- **`access`**: `sub` (UUIDv7 user id, or `guest:<emailhash>` for guests), `kind`
  (`user`/`guest`), `sid` (session id when `kind=user`), optional `tg_id`, `email`
  (hashed for guests).
- **`refresh`**: only `sub`, `sid`, `jti`. No PII.
- **`guest`**: `sub=guest:<emailhash>`, `email_hash`, `scope=["orders:create",
"orders:read:own"]`.
- **`ws-handshake`**: `sub`, `sid`, `channel` (e.g. `orders:{user_id}`).

`emailhash = sha256(lowercased_email + pepper)` truncated to 16 bytes / base64url. The
plaintext email never travels in a JWT.

### Rotation policy

- **Access**: stateless. To revoke, push the `jti` into Redis blocklist
  `auth:revoked:{jti}` with TTL = remaining lifetime.
- **Refresh**: **rotate on every use**. On `POST /auth/refresh`:
  1. Lookup `auth_sessions` row by SHA-256 hash of the supplied refresh token.
  2. If not found, expired, or revoked → 401 + log + (optionally) alert (signal of theft).
  3. Mark current row `revoked_at = now()`.
  4. Mint new access + new refresh. Persist a new `auth_sessions` row keyed by the new
     refresh hash. Return both.
- **Logout** (`POST /auth/logout`): mark current refresh as revoked; also blocklist the
  current access `jti`.
- **Refresh reuse detection**: if a refresh whose row is already `revoked_at` is presented,
  treat the **whole user session lineage** as compromised — revoke every active session
  for that user and force re-auth.

### Storage

- Refresh tokens are **never** stored in plaintext; only `sha256(token)` lives in
  `auth_sessions.refresh_token_hash`.
- `auth_sessions` schema is in the auth module's migration; see
  [migration 0001](../../apps/api/migrations/versions).
- Redis: `auth:revoked:{jti}` for access blocklist (TTL = access TTL).
  See `docs/architecture/cache-keys.md`.

### Transport

| Surface     | Header                                                                                                                                                                                   |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Web (user)  | `Authorization: Bearer <access>`                                                                                                                                                         |
| Web (guest) | `Authorization: Guest <access>` (same JWT, different prefix for clarity)                                                                                                                 |
| Mini App    | `Authorization: tma <raw initData>` — backend validates HMAC per request, mints a fresh access from the validated initData on demand. The Mini App **does not** receive a refresh token. |
| WebSocket   | `?token=<ws-handshake>` query param on the upgrade                                                                                                                                       |

Telegram Mini App is special: because Telegram itself signs `initData` on every open, we
treat the SDK's `initData` string as the "refresh credential" and re-mint short access
tokens server-side. No long-lived refresh is issued to the mini-app surface.

## Consequences

- All verifiers (current monolith + future services) only need the **public** key.
- Revocation works in both "lazy" (TTL expiry) and "active" (blocklist + DB revoke) modes.
- The refresh-reuse trip-wire turns token theft into an alert rather than a silent breach.
- Slight cost: every refresh writes one row to `auth_sessions` (cheap; partitionable
  later).
- Guest checkouts always cost a Redis read on subsequent calls (no harder than a session
  store).

## Alternatives considered

- **HS256 (shared secret)** — rejected: every microservice would have to hold the signing
  secret; key rotation becomes a multi-service synchronisation problem.
- **RS256** — workable, but keys are larger and signing is slower than Ed25519 with no
  upside for our scale.
- **Opaque tokens + central session lookup** — rejected at MVP: extra latency on every
  request and a single point of failure. We can adopt later for sensitive routes if
  needed.
- **Browser cookies for access tokens** — rejected at MVP: CSRF surface and SameSite
  edge-cases with the Telegram Mini App. Refresh is in a cookie (`HttpOnly`, `Secure`,
  `SameSite=Lax`) on the web; access stays in the `Authorization` header.

## References

- [ADR-0002](./0002-use-modular-monolith.md)
- [`apps/api/src/yupay/modules/auth/`](../../apps/api/src/yupay/modules/auth)
- [`docs/architecture/cache-keys.md`](../architecture/cache-keys.md)
- [Telegram Bot API — Validating data received via the Mini App](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app)
- [Telegram Bot API — Login Widget](https://core.telegram.org/widgets/login#checking-authorization)
