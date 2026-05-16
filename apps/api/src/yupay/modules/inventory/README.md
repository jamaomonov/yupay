# `inventory` — own warehouse of voucher codes

Хранит выкупленные оптом коды (Netflix, Spotify, Steam Wallet, и т.п.) и
выдаёт их в момент фулфилмента заказа. **Этап 1 — скелет** (ADR-0015).

## Шифрование

Коды лежат в БД зашифрованные XSalsa20-Poly1305 (`nacl.secret.SecretBox`).
Каждая строка несёт свой 24-байтовый nonce. Ключ берётся из `INVENTORY_ENC_KEY`
(env / Docker secret), 32 байта в base64. В dev/test пустой ключ деривится из
`AUTH_EMAIL_PEPPER` чтобы тесты не требовали отдельной настройки. В **prod**
пустой `INVENTORY_ENC_KEY` — отказ при старте.

Cleartext код существует в памяти **только** на время одного вызова
`reserve_and_issue` / `bulk_upload` / `list_codes_admin`. Логи и аудит не
пишут код. Ротация ключа — отложена в ADR-0020 (`key_version` колонка).

## Таблицы

| Таблица | Что |
|---|---|
| `inventory_codes` | один код. `state` ∈ `available / reserved / issued / voided`. UNIQUE по `(sku_id, code_hash)` ловит дубли. Partial INDEX `(sku_id, created_at) WHERE state='available'` — горячий путь резерва. |
| `inventory_uploads` | аудит-строка на каждый bulk-upload. `total / succeeded / duplicates`. |

## Сервис

```python
async def bulk_upload(db, *, sku_id, codes, uploaded_by) -> BulkUploadResult: ...
async def reserve_and_issue(db, *, sku_id, order_item_id) -> IssuedCode: ...
async def void_for_order_item(db, *, order_item_id, reason) -> int: ...
async def counts_for_sku(db, sku_id) -> SkuCounts: ...
async def list_codes_admin(db, *, sku_id=None, state=None, limit=50) -> [(InventoryCode, code)]: ...
async def get_code_for_order_item(db, order_item_id) -> str | None: ...
```

`reserve_and_issue` атомарен через `SELECT … FOR UPDATE SKIP LOCKED LIMIT 1` —
параллельные воркеры не блокируют друг друга и не выдают один код дважды.
Идемпотентен per `order_item_id`: повторный вызов отдаёт уже выданный код, не
расходуя второй.

Лимит на одну `bulk_upload` — 5000 кодов (см. `MAX_BULK`).

## HTTP (admin only)

```
POST   /api/v1/admin/inventory/bulk-upload       — { sku_id, codes: [...] }
GET    /api/v1/admin/inventory/sku/{sku_id}      — { available, reserved, issued, voided }
GET    /api/v1/admin/inventory/codes?sku_id=&state=&limit=
```

`GET /codes` показывает **cleartext** — админ по определению им доверен.

## Связь с `fulfillment`

`fulfillment.service.process_task` спрашивает `sourcing.resolve_for_sku` и:
- если decision.primary = `inventory` → вызывает `inventory.reserve_and_issue`,
  складывает результат в `deliveries(artifact_kind='voucher_code', source='inventory')`;
- на `NoStockError`:
  - `strict=False` (mode=auto) → переключается на `decision.fallback` (по умолчанию `mock`);
  - `strict=True` (mode=force_inventory) → task падает с `last_error='no stock and sourcing rule is strict'`.

## Что отложено

1. **Pre-reservation на чекауте** — резервировать в момент создания заказа, чтобы гарантировать stock по показанной пользователю цене. Нужен hook в `orders.service.create_order`.
2. **Code-expiry sweeper** — планировщик, который воидит коды с `expires_at < now()`.
3. **Key rotation** — ADR-0020.
4. **CSV/file upload** — пока только JSON-массив.
5. **Low-stock alerts** — Prometheus-метрика + правило в Alertmanager.
