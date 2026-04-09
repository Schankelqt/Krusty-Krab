# MVP Product Logic (OpenClaw Telegram Bot)

Этот файл — единый источник правды по продуктовой логике MVP.
Обновляется при каждом изменении логики в коде.

**Настройка окружения (Telegram, БД, Redis, ЮKassa, Ollama, OpenClaw):** см. [`Setup-Guide.md`](./Setup-Guide.md).

## 1) Роли и доступ

- Пользователь взаимодействует только через Telegram-бота.
- В internal-режиме (`INTERNAL_TEST_MODE=true`) доступ ограничен `INTERNAL_WHITELIST_IDS`.
- Админ может выдать доступ через `/admin_grant <telegram_user_id>`.

## 2) Главный флоу пользователя

1. Пользователь открывает бота и получает приветствие + меню.
2. В меню есть:
   - `BTN_TRIAL` (по умолчанию: "🪄 Познакомиться с OpenClaw")
   - `BTN_PLANS` (по умолчанию: "💳 Тарифы и оплата")
3. До оплаты пользователь может использовать триал.
4. После оплаты пользователь работает в платном режиме.

## 2.1) Оплата (ЮKassa)

- Кнопка `BTN_PLANS` показывает **сетку**: линии **GPT / Claude / Gemini** × пакеты **1M / 2M / 3M** токенов за период (`basic` / `standard` / `pro`).
- После выбора создаётся платёж в ЮKassa, пользователю отправляется ссылка на оплату.
- Работает только если заданы `YUKASSA_SHOP_ID` и `YUKASSA_SECRET_KEY` (`yukassa_configured`).
- Суммы в рублях задаются сеткой `BILLING_{GPT,CLAUDE,GEMINI}_{BASIC,STANDARD,PRO}_RUB`, валюта `YUKASSA_CURRENCY`.
- В метаданные платежа попадают `plan`, `llm_line` (`gpt` | `claude` | `gemini`) и `telegram_user_id`; при успехе обновляются `users.plan`, `users.billing_llm_line`, строка в `payments`. `YUKASSA_PLAN` — запасной вариант в вебхуке, если `plan` в метаданных нет.
- После оплаты ЮKassa шлёт уведомление на `POST /webhooks/yookassa` (FastAPI в том же процессе, что бот).
- В кабинете ЮKassa нужно зарегистрировать URL вебхука: `https://<домен>/webhooks/yookassa` (порт 8080 проброшен в `docker-compose`).
- Повторная проверка: после вебхука статус платежа запрашивается через API ЮKassa (`GET /v3/payments/{id}`).
- Успех: вызывается та же активация подписки, что и у `/admin_grant` (`activate_paid_subscription`), пользователю уходит сообщение в Telegram.
- Таблица `payments` хранит `yookassa_payment_id`, статус `pending` / `succeeded` / `canceled`.
- `BILLING_HTTP_ENABLED=false` отключает поднятие HTTP (только long polling бота).

## 3) Триал

- Запускается вручную кнопкой `BTN_TRIAL`.
- Параметры:
  - длительность: `TRIAL_DURATION_HOURS` (по умолчанию 24 часа)
  - лимит сообщений: `TRIAL_MESSAGE_LIMIT` (по умолчанию 50)
  - провайдер: `TRIAL_PROVIDER` (по умолчанию `ollama`)
- Триал одноразовый:
  - если `trial_started_at` уже установлен и триал завершен, повторно не стартует.

## 4) Soft mode после триала

- Если триал закончился и оплаты нет, доступ остается ограниченно открытым.
- Лимит: `SOFT_DAILY_MESSAGE_LIMIT` (по умолчанию 3 сообщения/день).
- Провайдер: fallback (`FALLBACK_PROVIDER`, обычно `ollama`).

## 5) Платный режим

- Активен, если:
  - `is_active = true`
  - текущее время внутри окна `[subscription_period_start, subscription_period_end)`.
- Внутри оплаченного периода:
  - пока не исчерпан лимит токенов за период по пакету пользователя (`users.plan`: basic=1M, standard=2M, pro=3M) -> провайдер по `users.billing_llm_line` (`gpt`→OpenAI, `claude`→Anthropic, `gemini`→Gemini) или, если линия пуста, глобальный `PRIMARY_PROVIDER` (например OpenClaw).
  - цены по умолчанию в коде: GPT pro **4 000 ₽** / 3M, Claude pro **5 000 ₽** / 3M, Gemini дешевле (см. `BILLING_*_RUB` в `core/config.py` и `.env.example`); лимиты токенов — `PAID_TOKEN_LIMIT_*`.
  - после достижения лимита -> fallback (`FALLBACK_PROVIDER`) с ограничением
    `PAID_FALLBACK_DAILY_MESSAGE_LIMIT` (по умолчанию 300 сообщений/день)

### OpenClaw как primary

- Для продакшн-флоу «после оплаты — OpenClaw» выставляют `PRIMARY_PROVIDER=openclaw`.
- Требуется поднятый Gateway с включённым HTTP endpoint `POST /v1/responses` (см. [OpenResponses API](https://docs.openclaw.ai/gateway/openresponses-http-api.md)).
- Переменные окружения:
  - `OPENCLAW_URL` — базовый URL Gateway (без завершающего `/`)
  - `OPENCLAW_API_KEY` — токен для `Authorization: Bearer ...` (режим `gateway.auth.mode=token` или `password` в Gateway)
  - `OPENCLAW_MODEL` — по умолчанию `openclaw`
  - `OPENCLAW_AGENT_ID` — опционально, заголовок `x-openclaw-agent-id`
- Сессия пользователя: стабильный ключ `telegram-{telegram_user_id}` в теле (`user`) и в `x-openclaw-session-key` (изоляция диалогов между пользователями).
- После первого успешного ответа в БД сохраняется `users.openclaw_session_id` (тот же ключ) для прозрачности в админке/отладке.
- Ответы провайдеров `openai`, `openclaw`, `anthropic`, `gemini` учитываются в одном лимите токенов периода (`metering_primary_providers` в коде).

## 6) Период подписки

- Логика окна подписки:
  - от даты/дня оплаты до того же числа следующего месяца
  - технически в коде: `[start_utc_00_00, next_month_same_day_utc_00_00)`
- Пример:
  - оплата 23.01 -> период до 23.02 00:00 UTC (последний полный день: 22.02 UTC).

## 7) Уведомления по токенам

- Для платного периода и primary-модели:
  - предупреждение при остатке ниже 20%
  - предупреждение при остатке ниже 5%
- Каждое предупреждение отправляется один раз за период (флаги в Redis).

## 8) Команды пользователя

- `/start` — приветствие и меню.
- `/tokens` — текущий статус лимитов:
  - в платном периоде: использовано/остаток токенов за период
  - в триале: прогресс триала
  - без периода: подсказка про старт триала/оплату.

## 9) Команды администратора

- `/admin_grant <telegram_user_id>`:
  - вызывает `activate_paid_subscription` без смены `plan` (если у пользователя план пустой — выставится `basic`).

## 10) Текущие ограничения MVP

- `/admin_grant` не меняет `plan`, если он уже задан; при пустом плане лимит токенов как у **Basic** (1M).
- Подпись тела вебхука ЮKassa не проверяется отдельно — опора на повторный `GET` платежа по API (для продакшена рассмотреть IP-фильтры ЮKassa).
- OpenClaw подключён как провайдер `openclaw` (HTTP к Gateway); при отсутствии URL/ключа или выключенном endpoint ответ будет ошибкой — проверяйте конфиг Gateway.
- В существующей БД нужно добавить сущности/колонки (если таблицы создавались до изменений):
  - таблица `payments`
  - колонки `users`: `subscription_period_start`, `subscription_period_end`, `trial_started_at`, `trial_message_count`

## 11) Правило сопровождения

- Любое изменение продуктовой логики в коде должно сопровождаться обновлением этого файла в том же изменении.
