# Себестоимость устарела (алерт `cost_stale`)

Сообщение «⏳ Себестоимость устарела» приходит в админ-чат, когда у активных SKU
поставщик не подтверждал закупочную цену дольше `COST_STALE_AFTER_HOURS` (6 ч).
Повторяется каждые 6 часов, пока проблема есть.

## Что это значит

- Часовой пересчёт берёт цену у маршрутного поставщика и пишет `cost_usdt`;
  каждая запись, даже без изменения, ставит `skus.cost_synced_at`.
- Если поставщик не отвечает (ключ протух, каталог переехал, 429 весь час),
  старая закупка остаётся, и от неё считаются розница, B2B-прайс и маржа.
  До 2026-10-05 это было не отличить от «цена стабильна».
- В алерте: сколько SKU, по каким поставщикам, восемь самых старых.

## Что делать

1. Открыть Интеграции → поставщика из алерта: баланс, ключ, последний ответ.
   `make logs service=scheduler`, искать `integrations.price_refresh.iteration_failed`.
2. Починить доступ, затем «Обновить цены» на странице поставщика или дождаться
   следующего часа. Алерт сам замолчит, когда stamp обновится.
3. Если SKU действительно не должен обновляться автоматически — закрепить его
   правилом сорсинга `force_inventory` или `manual`: такие исключаются. Исключается
   и `force_supplier` на поставщика без сбора цен (`manual`, `mock`, `waxpeer`):
   первый тик на проде поймал ровно такой `hok-16`, это не устаревание.
4. Второй случай с первого тика — настоящий: `garena-free-fire-weekly-lite`
   закреплён на `gengine`, но G-Engine цену на маппинг `46/389` не отдаёт, и
   `cost_usdt` там от G2B. Такой SKU либо переводят на поставщика, который
   отвечает, либо чинят маппинг.

## Полный список

```sql
select b.slug, s.sku_code, s.cost_synced_at,
       (select string_agg(m.supplier_slug, ',') from sku_supplier_mappings m
         where m.sku_id = s.id and m.is_active
           and m.supplier_slug in ('g2b','gengine','nova','fzr')) as suppliers
from skus s join products p on p.id = s.product_id join brands b on b.id = p.brand_id
where s.active and not s.variable_amount and s.cost_usdt is not null
  and (s.cost_synced_at is null or s.cost_synced_at < now() - interval '6 hours')
order by s.cost_synced_at nulls first;
```

## Настройки

- `COST_STALE_AFTER_HOURS` — порог; `0` выключает.
- Дедуп в Redis: `alert:cost_stale`, 6 ч. Удалить ключ, чтобы получить алерт сразу.
- Бэкфилл при миграции `0095`: последняя строка `supplier_price_history` по SKU,
  иначе момент миграции.
