# Redis Cache Keys Catalogue

> Every Redis key used by any module **must** appear in this table. New keys without a row
> here are rejected in code review. Keep the table sorted alphabetically by key prefix.

| Key pattern | Module | Type | TTL | Invalidation rule | Notes |
|---|---|---|---|---|---|
| `fx:rate:{base}:{quote}` | `fx` | string (JSON) | 15 min | Refreshed by `fx_refresh` periodic job every 5 min | Hot read path; falls through to `:stale` |
| `fx:rate:{base}:{quote}:stale` | `fx` | string (JSON) | 24 h | Same job that writes the fresh key | Last-known-good for graceful degradation |
| `auth:session:{session_id}` | `auth` | hash | 30 days | On logout / refresh rotation | Refresh token hash, IP, UA |
| `auth:revoked:{jti}` | `auth` | string | until JWT expiry | On manual revocation | Access token blocklist |
| `ratelimit:{route}:{ip}` | `core` | token bucket | sliding | — | slowapi |
| `idem:{user_id}:{route}:{key}` | `core` | hash | 24 h | Manual via admin tooling | Mirror of `idempotency_keys` for fast read |
| `orders:status:{order_id}` | `orders` | string (FSM) | 1 h | Invalidated on every order event | Hot read for WS fan-out |
| `catalog:product:{locale}:{id}` | `catalog` | string (JSON) | 10 min | Invalidated by `catalog.product.updated` event | Storefront page data |
| `inventory:available:{sku_id}` | `inventory` | int | 30 s | Invalidated on reservation/issue | Cheap "in stock" check; authoritative read is in DB |
| `wallet:balance:{user_id}:{currency}` | `wallet` | string (Decimal) | 5 min | Invalidated on any posting | Lazy projection; cold computed via SUM |
| `ws:channel:{channel}` | `realtime` | pubsub | — | — | Redis pub/sub channel, not a regular key |

## Conventions

- All keys are colon-separated; **no spaces or trailing slashes**.
- Prefix is **always the owning module's name**.
- Numeric TTLs are explicit in seconds inside the codebase (no implicit "forever" keys).
- Multi-key writes that must succeed atomically use Lua scripts; the script source lives under
  `apps/api/src/yupay/modules/<module>/scripts/`.
