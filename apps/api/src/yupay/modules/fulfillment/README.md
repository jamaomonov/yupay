# `fulfillment` — skeleton

Саговый оркестратор YuPay. **Этап 1 — скелет** (ADR-0013): фиксируем схему БД,
контракт `Fulfiller`, HTTP-роуты, FSM-переходы заказа после оплаты и аудиторскую
таблицу. Все реальные поставщики (Steam, Riot, PUBG/Tencent, Spotify, Apple,
voucher-warehouse) заглушены — слоты зарезервированы.

См.
[`docs/decisions/0013-fulfillment-skeleton-and-provider-stubs.md`](../../../../../docs/decisions/0013-fulfillment-skeleton-and-provider-stubs.md).

## Что делает модуль

1. Получает сигнал «order paid» от `payments._mark_payment_succeeded` (сегодня —
   прямой in-process вызов; завтра — outbox + Dramatiq).
2. Создаёт `FulfillmentTask` на каждый `OrderItem` (1-to-1, UNIQUE).
3. Двигает order `paid → fulfilling`.
4. Для каждого task: маршрутизирует к `Fulfiller` (сейчас всегда `mock`),
   вызывает `fulfill(order, item, idempotency_key=task.id)`, пишет
   `FulfillmentAttempt`, обновляет статус task'а, пишет `Delivery` с артефактом.
5. Когда все tasks `succeeded` — order `fulfilling → delivered`.

> **Manual-завершение и дубликаты.** `complete_manual_task` пишет `Delivery`
> внутри SAVEPOINT, открытого **до** `db.add(...)`: `begin_nested()` делает
> autoflush уже накопленного состояния, поэтому поздний savepoint позволил бы
> упавшему INSERT отравить всю request-транзакцию. Конфликт по
> `UNIQUE(order_item_id)` откатывает только этот блок и отвечает 409.

## Контракт `Fulfiller`

```python
class Fulfiller(Protocol):
    supplier: str

    @property
    def available(self) -> bool: ...

    async def fulfill(*, order, item, idempotency_key: str) -> FulfillResult: ...
    async def check_status(*, task) -> FulfillStatus: ...
    async def cancel(*, task) -> None: ...
```

`FulfillResult` несёт `outcome` (`succeeded` / `in_progress` / `failed`),
`external_order_id`, опциональный `artifact_kind` + `artifact` (для `voucher_code`,
`topup_receipt`, `license_key`).

### Поставщики

| Slug                | Статус                     | Что делает                                                            |
| ------------------- | -------------------------- | --------------------------------------------------------------------- |
| `mock`              | функционален в dev/staging | сразу возвращает `succeeded` + фейковый ваучер `MOCK-<order_item_id>` |
| `steam`             | заглушка                   | `available=False`, все методы → `FulfillerNotIntegratedError`         |
| `riot`              | заглушка                   | то же                                                                 |
| `pubg`              | заглушка                   | то же (Tencent / Midasbuy)                                            |
| `spotify`           | заглушка                   | то же                                                                 |
| `apple`             | заглушка                   | то же                                                                 |
| `voucher_inventory` | заглушка                   | подберёт код из будущего модуля `inventory`                           |

Реестр в `suppliers/__init__.py:REGISTRY`. Добавление нового поставщика =
реализовать класс + зарегистрировать slug.

## Таблицы

| Таблица                | Что хранит                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `fulfillment_tasks`    | один task на `OrderItem` (UNIQUE), `status` ∈ pending/in_progress/succeeded/failed/cancelled, `supplier`, `external_order_id`, `attempts_count`, `metadata jsonb`, таймстемпы (`succeeded_at`/`failed_at`/`cancelled_at`). Partial UNIQUE `(supplier, external_order_id) WHERE NOT NULL`.                                                                                                                                                                            |
| `fulfillment_attempts` | аудит обращений к поставщику (`kind` ∈ fulfill/status_check/cancel, `status` ∈ ok/error, `payload jsonb`, `error text`). **Не строка на тик:** повтор, идентичный предыдущей записи задачи, сворачивается в неё через `repeat_count` + `last_seen_at` (миграция 0045). Поллер спрашивает статус раз в минуту, пока заказ у поставщика открыт, — одна прод-задача накопила так 1641 строку, из них 1640 одинаковых. `attempts_count` считает строки, а не наблюдения. |
| `deliveries`           | финальный артефакт. UNIQUE `(order_item_id)`. `channel` (today всегда `in_app`), `artifact_kind`, `artifact jsonb`.                                                                                                                                                                                                                                                                                                                                                  |

> **Whitelist на клиентском API.** `GET /orders/{id}/deliveries` отдаёт `artifact`
> строго через allow-list `_CUSTOMER_SAFE_ARTIFACT_KEYS` (`routes.py`): наружу
> идут только `code`/`codes`/`key`/`pin`/`serial`/`steam_login`/`login`/
> `message`/`note`/`fulfillment_data`. `source` (апстрим-поставщик) и любые
> внешние/внутренние id (`external_id`, `external_order_id`,
> `inventory_code_id`, `sku_id`, `catalogue_name`, raw `amount_units`) —
> admin-only, видны через `/admin/fulfillment`. Новое поле от поставщика по
> умолчанию скрыто, пока не добавлено в whitelist явно.

Миграция: `0008_fulfillment_init`.

## Оповещения об ошибках

Любая ошибка фулфилмента уходит в ops-чат Telegram сразу — и та, где вызов
поставщика упал, и та, где вызов прошёл, а поставщик **ответил** отказом. Обе
пишут `status="error"` в `fulfillment_attempts`, поэтому алерт висит на
`_record_attempt`, а не на списке мест, который кто-то должен не забыть
дополнить.

Повторы гасятся дважды. Подряд идущие одинаковые ошибки вообще не доходят до
алерта — они сворачиваются в одну строку лога (см. миграцию 0045). Redis-дедуп
по `(задача, шаг, текст ошибки)` на час прикрывает «мигание» (ошибка →
восстановление → та же ошибка) и второго воркера. Другая ошибка — другой
инцидент, о нём сообщат сразу.

Алерт не может уронить продажу: любое исключение внутри него проглатывается и
логируется. В сообщение не попадает `fulfillment_data` — там Steam-логин и
игровые id (§9); текст ошибки поставщика включён и обрезан, потому что именно
он говорит, что делать.

## FSM (после оплаты)

```mermaid
stateDiagram-v2
    paid --> fulfilling : start_for_order
    fulfilling --> delivered : все tasks succeeded → in-app delivery
    fulfilling --> failed   : (вне скелета — retries не реализованы)
    fulfilling --> refunded : полный refund → cancel_open_tasks_for_order
    paid --> refunded : полный refund
```

`order.delivered_at` ставится одновременно с `order.fulfilled_at`. Скелет не
разделяет «fulfilled» (артефакт сформирован) и «delivered» (юзер получил) — пока
канал доставки только `in_app` (артефакт лежит в `deliveries` и доступен
владельцу заказа).

## Идемпотентность

- `fulfillment_tasks.order_item_id` UNIQUE — повторный `start_for_order` для
  того же заказа ничего не плодит.
- `(supplier, external_order_id)` partial UNIQUE — реконсилер безопасно ретраит
  `check_status`.
- `Fulfiller.fulfill` получает `idempotency_key = task.id` — детерминированно по
  task'у, поэтому ретраи у провайдера попадают в ту же запись.

## HTTP

```
GET  /api/v1/orders/{order_id}/deliveries          — owner-only, список артефактов
GET  /api/v1/admin/fulfillment/tasks               — admin
GET  /api/v1/admin/fulfillment/tasks/{id}          — admin detail + attempts
POST /api/v1/admin/fulfillment/tasks/{id}/retry    — admin перезапуск failed
POST /api/v1/admin/fulfillment/tasks/{id}/cancel   — admin отмена pending/failed
POST /api/v1/admin/fulfillment/tasks/{id}/complete — manual: создать Delivery, завершить
POST /api/v1/admin/fulfillment/tasks/{id}/fail     — manual: отметить как failed с причиной
```

## Ручная выдача (`supplier="manual"`)

Для SKU без supplier-API: правило sourcing'а `mode="manual"` (см.
[`sourcing/README.md`](../sourcing/README.md)) маршрутизирует задачу на
`ManualFulfiller`. Он всегда возвращает `outcome="in_progress"` — task
паркуется в админской очереди (`/admin/fulfillment/tasks?supplier=manual&status_filter=in_progress`).

Админ обрабатывает заказ:

- **Завершить** → `POST /complete` с `{artifact_kind, artifact, channel?, admin_note?}`.
  Создаётся `Delivery`, task → `succeeded`, item → `delivered`, и
  `_try_settle_order` продвигает заказ до `delivered` тем же путём, что и для
  обычных supplier-задач.
- **Отклонить** → `POST /fail` с `{reason, admin_note?}`. Task → `failed`,
  `last_error = reason`, item → `failed`. Заказ остаётся в `fulfilling` —
  рефанд (если нужен) админ инициирует отдельно через
  `/admin/payments/{id}/refund`, чтобы деньги и выдача оставались под
  раздельным контролем.

Оба эндпоинта guard'ятся `supplier == "manual" AND status == "in_progress"`,
двойной `complete` ловится UNIQUE(`order_item_id`) на `deliveries`.
Метаданные ручной обработки (`admin_note`, `completed_by`) сохраняются в
отдельных колонках на `fulfillment_tasks` — не в `extra_metadata`, чтобы
не пересекаться с merged-метаданными supplier'а.

## Каскадная отмена (отмена заказа / возврат)

Когда заказ завершается «отрицательно» — админ отменяет его или делает **полный**
возврат — открытые задачи фулфилмента отменяются автоматически, чтобы сага не
продолжала пытаться доставить (или не зависала в `failed`) товар, которым клиент
больше не владеет:

- `payments.service.refund_admin` при **полном** возврате (`is_full`) зовёт
  `cancel_open_tasks_for_order(order_id, reason="refund:<payment_id>")`. Частичный
  возврат оставляет заказ `delivered` и задачи не трогает.
- `orders.service.cancel_order_admin` зовёт
  `cancel_open_tasks_for_order(order_id, reason="order_cancelled")`. Сегодня отмена
  легальна только из `pending_payment` (задач ещё нет) — вызов идемпотентен и пока
  no-op, но контракт зафиксирован на будущее.

`cancel_open_tasks_for_order` проходит по всем задачам заказа и для каждой
не-терминальной (`pending`/`in_progress`/`failed`) выполняет тот же
`_apply_cancel`, что и админская кнопка `/cancel`: best-effort вызов
`Fulfiller.cancel`, затем `task.status=cancelled` и `order_item.fulfillment_state
= failed` (в `ck_order_items_state` нет значения `cancelled`). Уже `succeeded`
задачи **пропускаются** — возврат денег не отзывает выданный код; так же
пропускаются уже `cancelled` (идемпотентность).

## Mock-flow (end-to-end в dev)

```mermaid
sequenceDiagram
    autonumber
    participant FE as Web/Admin
    participant API as FastAPI
    participant PAY as payments.service
    participant FUL as fulfillment.service
    participant DB as Postgres
    participant MOCK as MockFulfiller

    FE->>API: webhook /webhooks/payments/mock {succeeded}
    API->>PAY: handle_webhook
    PAY->>DB: payments.status=succeeded
    PAY->>DB: orders.status=paid + order_events(order.paid)
    PAY->>FUL: start_for_order(order_id)

    FUL->>DB: INSERT fulfillment_tasks per item
    FUL->>DB: orders.status=fulfilling + order_events(order.fulfilling)
    loop per item
      FUL->>MOCK: fulfill(order, item, idempotency_key=task.id)
      MOCK-->>FUL: FulfillResult(succeeded, artifact)
      FUL->>DB: fulfillment_attempts(ok) + tasks.status=succeeded
      FUL->>DB: INSERT deliveries(channel=in_app, artifact)
      FUL->>DB: order_items.fulfillment_state=delivered
    end
    FUL->>DB: orders.status=delivered + order_events(order.delivered)
    API-->>FE: 200 {status: processed}
```

## Что в проде НЕ работает

- `mock` отключается при `Settings.is_prod`.
- Все stub-провайдеры отказывают (`available=False`).
- Скелет НЕ имеет retry-policy: failed task ждёт admin'а.

## Следующий шаг

Первый реальный адаптер — выбор по приоритету (PUBG/Tencent для UC топ-апов,
Steam для геймерских ключей, или voucher_inventory как самый автономный). Создать
`suppliers/<name>.py`, реализовать `Fulfiller`, написать contract-тесты
(success / retryable failure / duplicate replay). Параллельно — переехать саму
саговую цепочку в Dramatiq actor через outbox, чтобы webhook-ответ не блокировался
на медленной интеграции.
