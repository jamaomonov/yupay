G2Bulk API — Документация для интеграции (агент)
Документ описывает интеграцию с публичным REST API сервиса G2Bulk для автоматизации покупок игровых пополнений (PUBG Mobile, Mobile Legends, Free Fire и др.) и цифровых ваучеров. Предназначен для использования агентом (LLM/бот/сервис), который выполняет операции от имени пользователя.

1. Общие сведения

Base URL: https://api.g2bulk.com/v1/
Формат: REST + JSON
Аутентификация: API-ключ в заголовке X-API-Key
Rate limit: 1000 запросов / 10 секунд на ключ
Поддерживается игр: 180+
Среднее время ответа: < 200 мс
Последнее обновление документации: 7 мая 2026

Получить ключ можно через Telegram-бота G2Bulk. Хранить ключ только на стороне агента (в секретах). Несколько неуспешных попыток аутентификации приводят к постоянному бану IP.

2. Аутентификация
   Все защищённые эндпоинты требуют заголовок:
   X-API-Key: <your_api_key>
   Дополнительно для эндпоинтов покупки рекомендуется идемпотентный ключ (UUID), который дедуплицирует повторные запросы в течение 30 минут:
   X-Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000
   Если ключ не передан — каждый запрос создаёт новый заказ и списание.

3. Обзор эндпоинтов
   КатегорияМетодПутьAuthПользовательGET/v1/getMe✅КатегорииGET/v1/category—Категория по IDGET/v1/category/:id—ТоварыGET/v1/products—Товар по IDGET/v1/products/:id—Покупка товараPOST/v1/products/:id/purchase✅Доставка/опрос заказаGET/v1/orders/:id/delivery✅История заказовGET/v1/orders✅Заказ по IDGET/v1/orders/:id✅Список игрGET/v1/games—Поля для игрыPOST/v1/games/fields—Серверы для игрыPOST/v1/games/servers—Валидация Player IDPOST/v1/games/checkPlayerId—Каталог номиналовGET/v1/games/:code/catalogue—ETA номиналаPOST/v1/games/eta—Заказ топ-апаPOST/v1/games/:code/order✅Статус топ-апаPOST/v1/games/order/status✅История топ-аповGET/v1/games/orders✅ТранзакцииGET/v1/transactions✅

Группа /v1/topup/_ (legacy: Free Fire, PUBG) отключена — использовать унифицированные /v1/games/_.

4. Профиль и баланс
   GET /v1/getMe
   Возвращает данные авторизованного пользователя и текущий баланс.
   Ответ:
   json{
   "success": true,
   "user_id": 123456789,
   "username": "johndoe",
   "first_name": "John Doe",
   "balance": 8.74
   }
   Рекомендация агенту: перед любой покупкой запрашивать getMe и проверять, что balance >= unit_price \* quantity (или цена номинала).

5. Каталог товаров (ваучеры)
   GET /v1/category
   Список категорий с количеством товаров.
   GET /v1/products и GET /v1/products/:id
   Список и детали товаров с полями: id, title, description, category_id, category_title, unit_price, image_url, stock.
   POST /v1/products/:id/purchase
   Покупка ваучера. Списание происходит при успехе.
   Тело:
   json{ "quantity": 5 }
   Ответ может прийти в одном из двух режимов:
   COMPLETED — выдача мгновенно (локальный инвентарь):
   json{
   "success": true,
   "order_id": 123,
   "transaction_id": 456,
   "product_id": 1,
   "product_title": "60 UC Voucher",
   "status": "COMPLETED",
   "delivery_items": ["KEY1", "KEY2", "KEY3"]
   }
   PENDING — отложенная выдача (нужен polling):
   json{
   "success": true,
   "order_id": 124,
   "transaction_id": 457,
   "product_id": 2,
   "product_title": "PSN $20 Gift Card",
   "status": "PENDING",
   "delivery_items": null,
   "poll_url": "/v1/orders/124/delivery"
   }
   Алгоритм агента:

Сохранить order_id, transaction_id.
Если status == "COMPLETED" — вернуть delivery_items пользователю.
Если status == "PENDING" — опрашивать poll_url каждые 2–5 секунд.

GET /v1/orders/:id/delivery
Возвращает коды по заказу. HTTP-коды:
HTTPЗначениеДействие агента200COMPLETED — коды готовыпрекратить polling, отдать delivery_items202PROCESSING — ещё в работеповторить через 2–5 сек410FAILED / REFUNDED / CANCELLEDпрекратить polling, сообщить о возврате404заказ не найден / не вашпрекратить polling, логировать ошибку

Коды доступны только 7 дней с момента created_at. Агент обязан сохранить их в собственном хранилище.

6. История заказов и заказ по ID
   GET /v1/orders
   Параметры: page (1), limit (50, max 100), search.
   Возвращает массив orders и блок pagination (page, limit, total, total_pages).
   GET /v1/orders/:id
   Детали конкретного заказа.

7. Игровые топ-апы
   GET /v1/games
   Список поддерживаемых игр. Каждая игра имеет id, code (например pubg_mobile, free_fire, mlbb, pubgm), name, image_url.
   POST /v1/games/fields
   Возвращает список обязательных полей для конкретной игры и заметки (notes).
   Запрос:
   json{ "game": "mlbb" }
   Ответ:
   json{
   "code": "200",
   "info": {
   "fields": ["userid", "serverid"],
   "notes": "Not available for Indonesia users"
   }
   }
   POST /v1/games/servers
   Список серверов, если требуется. Если игра не имеет серверов — возвращается 403 (это не ошибка, а сигнал «сервер не требуется»).
   POST /v1/games/checkPlayerId
   Валидация ID игрока до создания заказа.
   json{
   "game": "mlbb",
   "user_id": "123456789",
   "server_id": "2001",
   "charname": "charname"
   }
   Ответ при успехе:
   json{ "valid": "valid", "name": "John Doe", "openid": "41581795132966184" }

charname зависит от игры (имя персонажа / сервер / идентификатор аккаунта). Реальное значение определяется по notes из /v1/games/fields.

GET /v1/games/:code/catalogue
Возвращает доступные номиналы (id, name, amount). Цены часто меняются вместе с курсом — агенту обязательно проверять цену непосредственно перед заказом.
POST /v1/games/eta (NEW)
Оценка времени выполнения для номинала.
json{ "game_code": "pubgm", "denom_id": "60" }
Ответ:
json{
"success": true,
"estimated_time": {
"label": "less_than_5_minutes",
"display": "Less than 5 minutes",
"median_seconds": 187
}
}
Возможные label: instant, less_than_1_minute, less_than_2_minutes, less_than_5_minutes, less_than_10_minutes, less_than_30_minutes, more_than_30_minutes, no_data.
POST /v1/games/:code/order
Создание топ-апа. Перед созданием API сам валидирует player ID и баланс.
Заголовки:
X-API-Key: <key>
X-Idempotency-Key: <uuid> # рекомендуется
Тело:
json{
"catalogue_name": "60 UC",
"player_id": "5679523421",
"server_id": "2001",
"charname": "charname",
"remark": "Optional note",
"callback_url": "https://your-domain.com/webhook/order-status"
}
Статусы заказа: PENDING → PROCESSING → COMPLETED или FAILED (с автоматическим возвратом баланса).
Webhook callback
Если передан callback_url, API отправит POST по достижении терминального статуса.

Метод: POST, JSON
Таймаут: 10 секунд
Политика повтора: 1 ретрай при ошибке/таймауте

Пример тела:
json{
"order_id": 42,
"game_code": "pubgm",
"game_name": "PUBG Mobile",
"player_id": "5679523421",
"player_name": "PlayerName",
"server_id": "2001",
"denom_id": "60 UC",
"price": 0.88,
"status": "COMPLETED",
"message": "Order completed successfully",
"remark": "your order remark",
"timestamp": "2024-01-15T10:30:00Z"
}
Webhook-эндпоинт агента должен:

отвечать 2xx в течение 10 секунд;
обрабатывать дубликаты (по order_id + status);
идемпотентно обновлять локальное состояние.

POST /v1/games/order/status
Проверка текущего статуса (если webhook не используется или для подстраховки).
json{ "order_id": 42, "game": "pubgm" }
⚠️ `order_id` в теле — ЧИСЛО, не строка. Строка ("42") → HTTP 400
`{"message":"Failed to parse request body"}`. `external_order_id` у нас — text,
поэтому клиент приводит его к int (`_numeric_order_id`).

⚠️ Форма ответа (create и order/status): объект заказа ОБЁРНУТ в ключ `order`,
рядом лежит `success` — а НЕ на верхнем уровне:
json{ "success": true, "order": { "order_id": 1309981, "status": "COMPLETED", "message": "..." } }
При этом ТЕЛО ВЕБХУКА — плоское (`order_id` на верхнем уровне). Несогласованность
реальная (проверено вживую на api.g2bulk.com). `getMe` тоже плоский. Клиент
разворачивает `order` через `_unwrap_order()`; читать поля с верхнего уровня
нельзя — иначе `external_order_id` сохранится как строка "None" и вебхук с
реальным id никогда не совпадёт (см. runbook g2b-troubleshooting).
GET /v1/games/orders
История топ-апов с пагинацией (page, limit, search). Поля каждого заказа включают order_id, game_code, player_id, player_name, denom_id, price, status, is_refunded, created_at, completed_at.

8. Транзакции
   GET /v1/transactions
   Параметры: page, limit, search. Возвращает движения баланса.
   Типы транзакций:

add_balance — пополнение (или возврат);
charge_balance — списание (покупка/топ-ап).

Поле status отражает успех операции (success и т. п.). Для каждой транзакции указаны balance_before и balance_after.

9. Обработка ошибок
   HTTPЗначениеРеакция агента200OKпродолжать400Bad Requestпроверить тело/параметры, не ретраить без правок401Unauthorizedпрекратить запросы, ключ неверный (риск IP-бана при повторах)404Not Foundобъект не существует / не принадлежит пользователю429Too Many Requestsэкспоненциальный backoff500Server Errorэкспоненциальный backoff, ограниченное число ретраев

403 на /v1/games/servers — это не ошибка валидации игры, а сигнал «серверы не нужны».

10. Рекомендованные сценарии для агента
    A. Покупка ваучера

GET /v1/getMe → проверка баланса.
GET /v1/products / /v1/category → выбор товара.
Сгенерировать UUID X-Idempotency-Key.
POST /v1/products/:id/purchase.
Если COMPLETED — вернуть коды. Если PENDING — polling GET /v1/orders/:id/delivery каждые 2–5 сек до 200/410.
Сохранить коды на своей стороне (окно 7 дней).

B. Игровой топ-ап

GET /v1/games → выбрать code.
POST /v1/games/fields → определить обязательные поля.
При необходимости POST /v1/games/servers.
POST /v1/games/checkPlayerId → подтвердить ник.
GET /v1/games/:code/catalogue → актуальная цена (+ опционально POST /v1/games/eta).
GET /v1/getMe → проверить баланс.
Сгенерировать UUID, POST /v1/games/:code/order с callback_url (если есть свой webhook).
Ожидать callback или опрашивать POST /v1/games/order/status.
На FAILED — баланс возвращается автоматически; уведомить пользователя.

C. Надёжность

Всегда использовать X-Idempotency-Key для всех POST-покупок.
На 429/5xx — экспоненциальный backoff (например 1с, 2с, 4с, 8с).
Не повторять запрос при 401/400 — это приведёт к бану IP.
Persisting: локально хранить order_id, ключи доставки, статусы, метки времени.
Webhook-обработчик: проверять подпись/источник на уровне сети (IP allowlist, секрет в URL), идемпотентно применять обновления.

11. Ограничения безопасности агента

Не логировать API-ключ и delivery_items в открытых каналах.
Не передавать ключ в URL/query — только в заголовке.
Не принимать callback_url от недоверенных пользователей без валидации (агент должен подставлять собственный endpoint).
Прекращать запросы при первом 401, чтобы избежать постоянного бана IP.
Соблюдать копирайт и условия использования платформы при перепродаже кодов.
