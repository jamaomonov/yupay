# `sourcing` — per-SKU fulfillment routing

Решает, **откуда брать товар** на каждую позицию заказа: со склада (`inventory`)
или через адаптер поставщика (`supplier:<slug>`). **Этап 1 — скелет** (ADR-0015).

## Правила

Одна таблица — `sku_sourcing_rules`:

| sku_id | mode                                                     | supplier_slug                                                | …   |
| ------ | -------------------------------------------------------- | ------------------------------------------------------------ | --- |
| UUID   | `auto` / `force_inventory` / `force_supplier` / `manual` | `mock` / `click` / `steam` / … (только для `force_supplier`) |     |

Отсутствие строки = режим `auto`.

## Decision

```python
@dataclass(frozen=True)
class Decision:
    primary: str           # 'inventory' | 'supplier:<slug>'
    fallback: str | None   # 'supplier:<slug>' | None
    strict: bool           # True → no fallback, fail the task on miss
    rule_present: bool
```

| mode                     | primary           | fallback        | strict  |
| ------------------------ | ----------------- | --------------- | ------- |
| `auto` (или нет правила) | `inventory`       | `supplier:mock` | `False` |
| `force_inventory`        | `inventory`       | `None`          | `True`  |
| `force_supplier`         | `supplier:<slug>` | `None`          | `True`  |
| `manual`                 | `supplier:manual` | `None`          | `True`  |

`mode="manual"` — для SKU без supplier-API. Slug у этого режима подразумеваемый
(всегда `manual`), `set_rule` форсит `supplier_slug=NULL`. Заказы по таким SKU
паркуются у `ManualFulfiller` в статусе `in_progress`, и админ обрабатывает их
из очереди ручной выдачи (см. `fulfillment/README.md`, секция «Ручная выдача»).

`DEFAULT_FALLBACK_SUPPLIER` сейчас захардкожен в `mock`. Когда появится первый
живой эквайринг — переедет в `Settings` (отдельный per-currency mapping).

## Сервис

```python
async def resolve_for_sku(db, sku_id) -> Decision: ...
async def set_rule(db, *, sku_id, mode, supplier_slug, admin_id) -> SkuSourcingRule: ...
async def get_rule(db, sku_id) -> SkuSourcingRule | None: ...
async def list_rules(db, limit=200) -> list[SkuSourcingRule]: ...
async def delete_rule(db, sku_id) -> None: ...
```

`set_rule` валидирует: `force_supplier` требует `supplier_slug`. На других режимах
переданный `supplier_slug` молча обнуляется, чтобы строка не несла мусора.

**`auto` теперь детерминирован, когда у SKU два активных маппинга.** До
ADR-0081 `_resolve_auto` брал первую строку `sku_supplier_mapping` без
`ORDER BY` — сходило с рук, пока у каждого top_up SKU был ровно один
активный маппинг. NOVA — первый **резервный** поставщик, и с ним у SKU
законно появляются два (например, `g2b` и `nova`) сразу. Без сортировки
ответ зависел бы от порядка, в котором Postgres решил вернуть строки, — он
может измениться после `VACUUM`, и ничто бы об этом не сообщило. Теперь
запрос сортируется `created_at ASC, supplier_slug ASC`: побеждает **самый
старый** активный маппинг — то есть действующий маршрут.

**Резервные поставщики исключены из этого выбора вообще** (`RESERVE_SUPPLIERS`
в `integrations.models`). Одной сортировки мало: она сохраняет маршрут
действующего поставщика, только пока тот вообще есть. У top_up SKU без
маппинга g2b — а это самое обычное состояние бренда — или у SKU, чей
единственный маппинг оператор отключил при переключении, самым старым
оказывается как раз резерв, и SKU начал бы молча покупать у поставщика,
которого никто не выбирал. Резерв достигается только явным
`force_supplier`.

## HTTP (admin only)

```
GET    /api/v1/admin/sourcing/rules                  — все явные правила
GET    /api/v1/admin/sourcing/rules/{sku_id}         — Decision (что сейчас применится)
PUT    /api/v1/admin/sourcing/rules/{sku_id}         — upsert
DELETE /api/v1/admin/sourcing/rules/{sku_id}         — снять, SKU вернётся в `auto`
```

`PUT` с `mode=force_supplier` на поставщика, которому нужен маппинг (G2B,
G-Engine, NOVA — `MAPPING_REQUIRED_SUPPLIERS` в `integrations.models`), отказывает, если
у SKU нет активной строки `sku_supplier_mapping` на него. Иначе правило
«применилось», а каждый заказ падает в inbox с `no active mapping` — по одному.
Waxpeer маппинга не требует и не проверяется.

## Связь с `fulfillment`

`fulfillment.service.start_for_order` зовёт `sourcing.resolve_for_sku(sku_id)`
для каждого item и пишет `fulfillment_tasks.supplier = 'inventory'` или
`fulfillment_tasks.supplier = '<slug>'`. Запись в `task.supplier` — это
**фактически выбранный маршрут**, не модель правила. При фолбэке (auto +
no-stock) `task.supplier` перезаписывается на slug провайдера, и в
`fulfillment_attempts` появляется строка `{route_switch: <slug>, reason: 'inventory_no_stock'}`.

## Что отложено

1. **Per-region routing** — сейчас правило per-SKU; для крупных каталогов
   нужно «все Spotify-региона EU → supplier:steam».
2. **Cost-based routing** — выбирать дешевле (наш склад vs supplier-margin),
   с фолбэком при изменении цен.
3. **A/B routing** — % трафика на нового поставщика для прогрева.
