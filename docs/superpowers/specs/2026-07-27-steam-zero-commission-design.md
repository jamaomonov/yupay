# Steam «0% комиссии за сумы» — Design Spec

**Date:** 2026-07-27
**Status:** Draft for review
**Surface:** `apps/web` (public storefront) + `apps/api` catalog module (one localized field)

## Goal

Профессионально подать УТП «пополнение Steam в Узбекистане за сумы — 0% комиссии»
на витрине: фокусная секция на главной + усиление уже существующей страницы
`/store/steam` (highlight-бэнд + SEO-контент), без дубля продуктовой страницы и без
каннибализации SEO.

## Business truth (единственный источник правды для копирайта)

- **0% = нет нашей комиссии сверху. 1:1.** Клиент платит ровно ту сумму, что зайдёт на
  Steam-кошелёк. Маржа зашита в курс; явного сервисного сбора нет.
- Не писать «0% на конвертацию» и не обещать «официальный курс Steam» — это не так.
  Формулировки строятся только вокруг «без комиссии сверху / сколько платите — столько
  заходит».
- Предыдущее значение «Комиссия — от 4%» на карточке Steam главной было **мок-данными** и
  правится на «0%» везде.

## Scope (утверждено: «максимум сразу»)

Четыре слоя. A и D — фронт-only. B — бэк-поле + фронт-рендер. C — контент-данные каталога.

### Слой A — Секция на главной `SteamZeroCommission` (frontend, RSC)

- **Файл:** `apps/web/src/components/sections/SteamZeroCommission.tsx` (RSC, без `"use client"`).
- **Приём:** value-бэнд + trust (утверждён). Композиция:
  - Крупный заголовок «0% комиссии — пополнение Steam за сумы» (H2, `font-display`).
  - Подзаголовок: 1:1, «сколько платите — столько заходит на баланс», оплата в сумах.
  - Ряд иконок платёжек: `public/payment/{click,payme,uzum,usdt}.png`.
  - Trust-чипы: «⚡ 1–3 минуты», «🔒 без пароля», «↩ гарантия возврата».
  - CTA «Пополнить Steam» → внутренняя ссылка `/${locale}/store/steam` (через `Link`).
  - Лого Steam: `public/brands/steam-mono.png` (чёрный круг на прозрачном фоне) — на тёмной
    секции рендерить как белый круг: либо `filter: invert(1)`, либо на светлой/лаймовой
    плашке-диске. Фон секции — `public/brands/steam-bg.jpg` с затемняющим градиентом (как
    hero бренда).
- **Дизайн-система:** только существующие токены (`text-primary`, `text-tx-mute`,
  `border-border`, glow lime/blue, `buttonStyles`). Никаких новых цветов вне палитры.
  Бюджет бандла: секция RSC, без клиентского JS (нет калькулятора) → нулевой прирост JS.
- **Размещение:** `apps/web/src/app/[locale]/page.tsx`, высоко — после `TrustBand`, перед
  `CatalogBento`.
- **i18n:** namespace `web.steamZero.*` (заголовок, подзаголовок, чипы, CTA, alt-тексты).
- **Тема:** секция коммитится в тёмный визуал витрины (как остальные секции главной) —
  single-theme в рамках сайта, консистентно с существующими.

### Слой B — Highlight-бэнд на `/store/steam` (backend поле + frontend рендер)

Переиспользуемое, i18n, без хардкода по slug.

- **Backend (`apps/api/src/yupay/modules/catalog/`):**
  - Новое локализованное поле `highlights: list[str]` на `BrandTranslation`.
    Хранение: `highlights_json` (`Text`/`JSON`, nullable) — короткий список коротких
    чипов («0% комиссии», «Оплата в сумах», «1–3 минуты», «Без пароля»).
  - Alembic-миграция (следующий номер после `0031`), forward-only, nullable-колонка
    (безопасно для существующих строк).
  - Схема `schemas.py`: `BrandDetailOut.highlights: list[str]` (default `[]`), сериализатор
    берёт локаль как остальные поля.
  - `service.py`: включить `highlights` в выборку detail. **Не** ломать list-эндпоинты
    (N+1: поле только в detail, translations уже подгружаются).
  - Реген: `make gen-api` → `docs/api/openapi.json` + `packages/api-client/`.
- **Frontend:**
  - `apps/web/src/lib/catalog.ts`: `BrandDetail.highlights?: string[]` — **ОБЯЗАТЕЛЬНО
    опционально** (SSG пре-рендерит против старого API, см. memory
    `web-ssg-prerenders-against-deployed-api`), в рендере `highlights ?? []`.
  - `apps/web/src/app/[locale]/store/[brandSlug]/page.tsx`: рендер чипов в hero-баннере,
    только если массив непустой → другие бренды не затрагиваются.
- **Наполнение:** для бренда `steam` заполнить `highlights` в 3 локали (SQL/seed, как
  прежние SEO-описания — hand-SQL, см. memory `web-store-api-and-db-enrichment`).

### Слой C — Усиление SEO-контента Steam (данные каталога, не код)

- Переписать `BrandTranslation` бренда `steam` (3 локали): `short_description`,
  `description`, `instructions` под ключ «пополнение Steam Узбекистан за сумы 0%»,
  естественное вхождение, без переспама.
- Обновить/дополнить `BrandFaq` бренда `steam` (3 локали): вопросы под интент («Есть ли
  комиссия?», «Можно ли платить в сумах?», «За сколько зачислится?», «Нужен ли пароль?»).
  FAQ автоматически идёт в `FAQPage` JSON-LD (уже реализовано на странице).
- Мета `/store/steam` формируется из `description` → усиливается автоматически (слой уже
  есть в `generateMetadata`).
- **Каталожная карточка главной:** правка `web.catalog.cards.steam.statCommission`
  «от 4%» → «0%» в `ru/en/uz`; при необходимости `steamDesc`.
- **Применение:** контент готовит SEO-субагент (копирайт), применяется на прод SQL/seed по
  команде пользователя (не в рамках CI-миграции данных).

### Слой D — Доверие (frontend, лёгкое)

- Опционально: 1–2 Steam-специфичных отзыва в существующей секции `Reviews` (i18n).
- Отдельной страницы/мета не создаём — цель ранжирования остаётся `/store/steam`.

## Data flow

```
Homepage (RSC) ── SteamZeroCommission ──CTA──▶ /store/steam
                                                     │
store/[brandSlug] (RSC) ─ getBrandDetail(steam) ─────┤
   ├─ hero: highlights[] chips  (Слой B)
   ├─ about/instructions/FAQ    (Слой C, из БД)
   └─ JSON-LD Product+Breadcrumb+FAQPage (существует)
API /catalog/brands/{slug} ─ BrandDetailOut.highlights (Слой B)
```

## i18n

- Новый namespace `web.steamZero.*` — все ключи в `ru/en/uz` в одном PR.
- Правка `web.catalog.cards.steam.statCommission` в 3 локалях.
- `highlights` и SEO-контент бренда — не в JSON-каталогах, а в БД (per-locale строки).
- Валюта/суммы — через `Intl.NumberFormat`/`formatUzs`, без строковой конкатенации.

## Assets

- ✅ `apps/web/public/brands/steam-mono.png` (получен, 800×800 RGBA).
- ✅ `apps/web/public/brands/steam-bg.jpg`, `public/payment/*.png` (уже в репозитории).
- Опционально от пользователя: более качественная фоновая графика секции (не блокер).

## Testing

- **Frontend:** тест рендера `SteamZeroCommission` (заголовок, CTA-ссылка на `/store/steam`,
  наличие иконок платёжек, i18n-ключи резолвятся). Тест highlight-чипов на brand-странице
  (рендерятся при непустом массиве, отсутствуют при пустом).
- **Backend:** тест схемы `BrandDetailOut.highlights` (default `[]`, локализация);
  тест миграции (upgrade/downgrade); отсутствие N+1 на list-эндпоинтах (существующий
  query-count тест не должен регрессировать).
- Покрытие: web ≥ 70%, api ≥ 80% (каталог — не в 95%-зоне payments/wallet).

## Docs (в том же PR)

- ADR на новое поле каталога `highlights` (`docs/decisions/NNNN-brand-highlights.md`, MADR).
- `docs/architecture/module-map.md` — при изменении контракта каталога.
- Реген `docs/api/openapi.json` (`make gen-api`).
- README модуля каталога — при необходимости.

## Execution model

Subagent-Driven Development. Профильные субагенты:
- **SEO-агент:** ключевая стратегия + копирайт `highlights`/description/instructions/FAQ в
  3 локали + проверка schema.org.
- **UI-агент:** визуал секции `SteamZeroCommission` в рамках дизайн-системы.
- Имплементер+ревьюер на каждую кодовую задачу; PM/координация — на ведущем.

## Out of scope

- Отдельный лендинг `/steam-popolnenie` (каннибализация `/store/steam`).
- Калькулятор/интерактив (при 1:1 не добавляет ценности; приём — value-бэнд).
- Изменение платёжной/фулфилмент-логики Steam (только подача/контент).
- Админ-UI редактирования `highlights` (первичное наполнение — SQL/seed; UI — отдельный
  бэклог при желании).

## Open items / решения для плана

1. Формат хранения `highlights`: `JSON`-колонка vs `Text` c разделителем — решить в плане
   (рекомендация: `JSON`/`JSONB`, чистее для списка).
2. Точное место чипов в hero brand-страницы (рядом с существующими `Chip` от/ETA/security).
3. Финальный список чипов Steam (черновик: «0% комиссии», «Оплата в сумах», «1–3 минуты»,
   «Без пароля»).
