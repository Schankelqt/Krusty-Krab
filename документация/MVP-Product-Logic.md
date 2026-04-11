# MVP Product Logic (OpenClaw Telegram Bot)

Этот файл — единый источник правды по продуктовой логике MVP.
Обновляется при каждом изменении логики в коде.

**Настройка окружения (Telegram, БД, Redis, ЮKassa, Ollama, OpenClaw):** см. [`Setup-Guide.md`](./Setup-Guide.md).

## 1) Роли и доступ

- Пользователь взаимодействует только через Telegram-бота.
- В internal-режиме (`INTERNAL_TEST_MODE=true`) доступ ограничен `INTERNAL_WHITELIST_IDS`.
- Админ: команды раздела 9 + панель **`/admin`** (лимиты, уведомления, доп. whitelist в БД).

## 2) Главный флоу пользователя

1. Пользователь открывает бота: при первом визите — **онбординг** (2 шага с inline-кнопками), затем reply-меню; при повторном `/start` — сразу подсказка по кнопкам.
2. В меню есть:
   - `BTN_TRIAL` (по умолчанию: "🪄 Познакомиться с OpenClaw")
   - `BTN_PLANS` (по умолчанию: "💳 Тарифы и оплата")
   - `BTN_AGENT_SETTINGS` (по умолчанию: "⚙️ Настройки ассистента") — персонализация агента OpenClaw (`/agent`), см. [`OpenClaw-Agent-Telegram.md`](./OpenClaw-Agent-Telegram.md)
3. До оплаты пользователь может использовать триал.
4. После оплаты пользователь работает в платном режиме.
5. Текст ответа LLM по умолчанию без суффикса `(provider=…, model=…)`; для отладки: `SHOW_LLM_DEBUG_IN_REPLY=true` в `.env`.

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
  - лимит токенов за период считается **только по ответам платных API** (`metering_primary_providers`: `openai`, `openclaw`, `anthropic`, `gemini`). Сообщения через **Ollama / mock** в этот лимит **не входят** (экономичный режим не «съедает» пакет).
  - пока не исчерпан лимит по этой метрике -> провайдер по `users.billing_llm_line` (`gpt`→OpenAI, `claude`→Anthropic, `gemini`→Gemini) или, если линия пуста, глобальный `PRIMARY_PROVIDER` (например OpenClaw).
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
  - **новая подписка или оплата после окончания предыдущего периода:** от даты/дня оплаты до того же числа следующего месяца — `[start_utc_00_00, start + 1 месяц)` (`subscription_window_from_payment`).
  - **продление при активном периоде:** если оплата приходит, пока `now` ещё внутри текущего `[subscription_period_start, subscription_period_end)`, следующий период начинается с **`subscription_period_end`** (без разрыва и без усечения оставшихся дней).
- Пример нового окна:
  - оплата 23.01 -> период до 23.02 00:00 UTC (последний полный день: 22.02 UTC).

## 7) Уведомления по токенам

- Для платного периода (по **метрируемым** токенам, см. §5):
  - предупреждение при остатке ниже 20%
  - предупреждение при остатке ниже 5%
  - срабатывают и в режиме Ollama-fallback после исчерпания пакета (остаток считается по платным API).
- Каждое предупреждение отправляется один раз за период (флаги в Redis).

## 8) Команды пользователя

- `/start` — приветствие и меню.
- `/help` — краткая справка по командам и кнопкам.
- `/tokens` — текущий статус лимитов:
  - в платном периоде: использовано/остаток токенов за период
  - в триале: прогресс триала
  - без периода: подсказка про старт триала/оплату.

## 9) Команды администратора

- **`/admin`** — панель настроек в Telegram: сводка по БД, пресеты лимитов (пишутся в `app_settings`), переключатели уведомлений команде и клиентам (напоминание за N дней до конца подписки), просмотр доп. whitelist и команды ниже.
- **`/whitelist_add` / `/whitelist_remove`** — дополнительные Telegram id при `INTERNAL_TEST_MODE` (хранятся в `app_settings`, не требуют правки `.env`).
- `/admin_grant <telegram_user_id>` — вызывает `activate_paid_subscription` без явного `plan` / `billing_llm_line` (если у пользователя план пустой — выставится `basic`).
- `/admin_grant <telegram_user_id> <basic|standard|pro>` — то же + явно задаёт `users.plan` (лимит токенов за период).
- `/admin_grant <telegram_user_id> <basic|standard|pro> <gpt|claude|gemini>` — то же + задаёт `users.billing_llm_line` (как после оплаты по сетке).
- `/admin_grant <telegram_user_id> <basic|standard|pro> -` (или `none` / `clear`) — активирует с выбранным планом и **сбрасывает** `billing_llm_line` (дальше платный primary = глобальный `PRIMARY_PROVIDER`).
- `/admin_revoke <telegram_user_id>` — `is_active=false`, очищены период подписки, `billing_llm_line`, план сброшен в **basic**; триал (`trial_started_at` / счётчик) **не** сбрасывается.

## 10) Текущие ограничения MVP

- Без аргумента плана `/admin_grant` не меняет уже заданный `plan`; при пустом плане лимит как у **Basic** (1M). С аргументом плана админ **перезаписывает** `plan`.
- Подпись тела вебхука ЮKassa не проверяется отдельно — опора на повторный `GET` платежа по API (для продакшена рассмотреть IP-фильтры ЮKassa).
- OpenClaw подключён как провайдер `openclaw` (HTTP к Gateway); при отсутствии URL/ключа или выключенном endpoint ответ будет ошибкой — проверяйте конфиг Gateway.
- В существующей БД нужно добавить сущности/колонки (если таблицы создавались до изменений):
  - таблица `payments` (в т.ч. `llm_line`)
  - колонки `users`: `subscription_period_start`, `subscription_period_end`, `trial_started_at`, `trial_message_count`, `billing_llm_line`, `openclaw_session_id`
  - таблица `bot_events` (метрики: тип события, user_id, JSON payload, время)

## 11) Напоминания клиентам и алерты команде

- **Клиенты:** при включённом пороге (по умолчанию 3 дня, настраивается в `/admin`) раз в час проверяются подписки, у которых скоро конец периода; одно напоминание на период (ключ в Redis).
- **Команда:** при включённых флагах в `/admin` — уведомление о новом пользователе (первый `/start`), об успешной оплате (вебхук), о необработанной ошибке в обработчике (глобальный error handler). Получатели: `ADMIN_TEAM_CHAT_ID` или личные сообщения всем `ADMIN_IDS`.

## 12) Метрики и отчётность

- При **`METRICS_ENABLED=true`** (по умолчанию) в таблицу **`bot_events`** пишутся события: `/start`, `/tokens`, whitelist, кнопки триала/тарифов, чекаут, оплата (успех/отмена/ошибка активации), отказы в доступе (код **`deny_reason`**), успешные ответы LLM (провайдер, токены, флаги лимитов), расход дневных лимитов (soft / paid fallback), предупреждения по токенам периода, **`admin_grant` / `admin_revoke`**, после успешной отправки — **`report_now_sent`**.
- Детальный учёт генераций по-прежнему в **`usage_logs`** (токены по провайдеру).
- **`METRICS_REPORT_ENABLED=true`** и **`METRICS_REPORT_CHAT_ID`**: раз в сутки в указанный UTC-час (**`METRICS_REPORT_HOUR_UTC`**) бот шлёт в канал HTML-сводку за последние 24 ч (события, usage_logs, оплаты по **`payments.updated_at`**, снимок числа пользователей и активных подписок). Канал: добавить бота администратором с правом публикации.
- Админ-команда **`/report_now`** — немедленно отправить ту же сводку в **`METRICS_REPORT_CHAT_ID`**.
- Опционально **`METRICS_INTERNAL_TOKEN`**: `GET /internal/metrics/summary` с заголовком **`Authorization: Bearer <token>`** — JSON со сводкой за 24 ч (для скриптов / дашбордов). Если токен пустой, ответ **404**.

## 13) Правило сопровождения

- Любое изменение продуктовой логики в коде должно сопровождаться обновлением этого файла в том же изменении.
