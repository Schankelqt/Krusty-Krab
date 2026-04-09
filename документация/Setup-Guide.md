# Инструкция по настройке проекта (чеклист)

Документ для команды: что включить и проверить перед запуском в бою.  
Сейчас можно ничего не настраивать — просто пройти список, когда будете готовы.

---

## 1. Локальная среда

- [ ] Установлены **Docker** и **Docker Compose** (или запуск без Docker: Python **3.11+**, отдельно Postgres и Redis).
- [ ] Склонирован репозиторий, в корне создан файл **`.env`** из шаблона:
  ```bash
  cp .env.example .env
  ```

---

## 2. База данных PostgreSQL

- [ ] В `.env` задан **`DATABASE_URL`** в формате asyncpg, например:
  - локально с `docker-compose`:  
    `postgresql+asyncpg://user:password@localhost:5432/assistant_db`  
    (логин/пароль/имя БД как в `docker-compose.yml` для сервиса `db`).
  - в проде — строка от хостинга (managed PostgreSQL).
- [ ] Первый запуск создаёт таблицы через **`create_all`** в коде. Если база уже существовала до появления новых полей/таблиц — выполнить **ручные миграции** (см. раздел «Миграции вручную» в конце).

---

## 3. Redis

- [ ] В `.env` указан **`REDIS_URL`**, например `redis://localhost:6379/0` (или имя сервиса `redis` внутри Docker-сети).

---

## 4. Telegram-бот

- [ ] В **BotFather** создан бот, скопирован **`BOT_TOKEN`** в `.env`.
- [ ] Для внутреннего теста:
  - [ ] **`INTERNAL_TEST_MODE=true`**
  - [ ] **`INTERNAL_WHITELIST_IDS`** — через запятую числовые **Telegram user id** (узнать у @userinfobot или аналога).
- [ ] Для продакшена: **`INTERNAL_TEST_MODE=false`** и пустой/неиспользуемый whitelist (логика доступа тогда без whitelist).
- [ ] **`ADMIN_IDS`** — через запятую ваши user id для команд `/admin_grant`, `/admin_revoke`, **`/report_now`** и т.д.
- [ ] Опционально **`ADMIN_TEAM_CHAT_ID`** — один чат/канал для алертов команды (бот — админ с правом писать). Иначе алерты уходят в личку каждому из `ADMIN_IDS`.

### Панель `/admin`

- [ ] Команда **`/admin`** открывает inline-меню: сводка, лимиты (триал / soft / paid fallback), уведомления, доп. whitelist.
- [ ] Настройки из панели пишутся в таблицу **`app_settings`** и перекрывают значения из `.env` (кеш ~25 с; кнопка «Сбросить кеш» в панели).

### Метрики и ежедневный отчёт в Telegram

- [ ] **`METRICS_ENABLED=true`** — события пишутся в таблицу **`bot_events`** (см. `MVP-Product-Logic.md` §11).
- [ ] Канал для отчётов: создать канал, добавить **бота администратором** с правом **публиковать сообщения**, скопировать id канала (часто вида **`-100…`**) в **`METRICS_REPORT_CHAT_ID`**.
- [ ] **`METRICS_REPORT_ENABLED=true`**, **`METRICS_REPORT_HOUR_UTC`** (0–23) — ежедневная сводка за последние 24 ч UTC. Для проверки после деплоя: **`METRICS_REPORT_ON_START=true`** (один отчёт через ~15 с после старта), затем выключить.
- [ ] Ручная отправка той же сводки: **`/report_now`** (из-под **`ADMIN_IDS`**).
- [ ] Опционально **`METRICS_INTERNAL_TOKEN`**: `curl -H "Authorization: Bearer <token>" http://localhost:8080/internal/metrics/summary` — JSON для внешних дашбордов.

---

## 5. ЮKassa (оплата)

- [ ] В личном кабинете ЮKassa взяты **`YUKASSA_SHOP_ID`** и **`YUKASSA_SECRET_KEY`** → в `.env`.
- [ ] **`BILLING_RETURN_URL`** — куда вернуть пользователя после оплаты (часто `https://t.me/YourBot`).
- [ ] **`BILLING_GPT_*_RUB`**, **`BILLING_CLAUDE_*_RUB`**, **`BILLING_GEMINI_*_RUB`** (сетка линия × пакет), **`YUKASSA_CURRENCY`**, при необходимости **`YUKASSA_PLAN`** (fallback в вебхуке).
- [ ] Поднят HTTP с вебхуком (порт **`API_PORT`**, по умолчанию **8080**):
  - [ ] В кабинете ЮKassa указан URL уведомлений:  
    `https://<ваш-домен>/webhooks/yookassa`  
    (домен должен смотреть на ваш сервер / прокси на порт 8080).
- [ ] Локальная отладка вебхука: **ngrok**, **Cloudflare Tunnel** и т.п. на `localhost:8080`.
- [ ] При необходимости отключить HTTP в одном процессе с ботом: **`BILLING_HTTP_ENABLED=false`** (тогда только long polling; оплата через ЮKassa без вебхука работать не будет).

---

## 6. LLM: Ollama (триал / fallback)

- [ ] Установлен **Ollama**, запущен сервис.
- [ ] В `.env`: **`OLLAMA_BASE_URL`** (локально часто `http://localhost:11434`; из Docker на хост — `http://host.docker.internal:11434` на macOS/Windows или IP хоста на Linux).
- [ ] В `.env`: **`OLLAMA_MODEL`** — имя модели, **уже скачанной** в Ollama (`ollama pull <имя>`).
- [ ] Для триала/фолбэка: **`TRIAL_PROVIDER=ollama`**, **`FALLBACK_PROVIDER=ollama`** (или `mock` для теста без железа).

---

## 7. LLM: платный primary (на выбор)

После оплаты по сетке в `users.billing_llm_line` хранится линия (`gpt` / `claude` / `gemini`); роутер ходит в **OpenAI / Anthropic / Gemini** соответственно. Если линия пуста (например выдали доступ через `/admin_grant`), используется глобальный **`PRIMARY_PROVIDER`**. Заполните ключи для тех линий, которые реально продаёте.

### Вариант A — OpenClaw Gateway

- [ ] Поднят **OpenClaw Gateway**, в конфиге включён **`POST /v1/responses`** (см. [документацию OpenClaw](https://docs.openclaw.ai/gateway/openresponses-http-api.md)).
- [ ] В `.env`: **`PRIMARY_PROVIDER=openclaw`**, **`OPENCLAW_URL`**, **`OPENCLAW_API_KEY`**, при необходимости **`OPENCLAW_MODEL`**, **`OPENCLAW_AGENT_ID`**.
- [ ] Автоустановка Docker + Gateway + подсказки по `.env`: **[`Server-Install.md`](./Server-Install.md)** (`scripts/install-server.sh`, `scripts/openclaw-gateway-bootstrap.sh`).

### Вариант B — OpenAI API

- [ ] **`OPENAI_API_KEY`**, **`OPENAI_MODEL`** (нужны для оплат с линией **GPT** или если **`PRIMARY_PROVIDER=openai`**).

### Вариант B2 — Anthropic (Claude)

- [ ] **`ANTHROPIC_API_KEY`**, **`ANTHROPIC_MODEL`** — для оплат с линией **Claude**.

### Вариант B3 — Google Gemini

- [ ] **`GEMINI_API_KEY`**, **`GEMINI_MODEL`** — для оплат с линией **Gemini**.

### Вариант C — только mock (разработка)

- [ ] **`PRIMARY_PROVIDER=mock`**, **`FALLBACK_PROVIDER=mock`** — без внешних сервисов.

---

## 8. Прочие лимиты и кнопки (по желанию)

См. **`.env.example`** и продуктовую логику в **`документация/MVP-Product-Logic.md`**:

- лимиты триала, soft mode, токены за период, тексты кнопок меню и т.д.

---

## 9. Запуск

- [ ] Из корня репозитория:
  ```bash
  docker compose --env-file .env up -d --build
  ```
- [ ] Проверка API: `GET http://localhost:8080/health` → `{"status":"ok"}`.
- [ ] В Telegram: **`/start`**, триал/оплата по сценарию.

---

## 10. Миграции вручную (если БД старше кода)

Если таблицы уже были без новых сущностей, добавьте недостающее SQL-ом (пример для PostgreSQL):

```sql
-- users (если колонок ещё нет)
ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_period_start TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_period_end TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_started_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_message_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS openclaw_session_id VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS billing_llm_line VARCHAR(16);

-- payments (если таблицы не было — проще пересоздать БД на пустом окружении)
CREATE TABLE IF NOT EXISTS payments (
  id SERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL,
  yookassa_payment_id VARCHAR(64) NOT NULL UNIQUE,
  status VARCHAR(32) NOT NULL DEFAULT 'pending',
  amount_value VARCHAR(32) NOT NULL,
  currency VARCHAR(8) NOT NULL DEFAULT 'RUB',
  plan VARCHAR(32) NOT NULL DEFAULT 'basic',
  llm_line VARCHAR(16),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_payments_user_id ON payments (user_id);

-- если таблица payments уже существовала без колонки линии
ALTER TABLE payments ADD COLUMN IF NOT EXISTS llm_line VARCHAR(16);

-- метрики (если таблицы ещё нет)
CREATE TABLE IF NOT EXISTS bot_events (
  id SERIAL PRIMARY KEY,
  event_type VARCHAR(64) NOT NULL,
  user_id BIGINT NULL,
  payload JSONB NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_bot_events_created_at ON bot_events (created_at);
CREATE INDEX IF NOT EXISTS ix_bot_events_event_type_created ON bot_events (event_type, created_at);
CREATE INDEX IF NOT EXISTS ix_bot_events_user_id_created ON bot_events (user_id, created_at);

-- онбординг (новые пользователи проходят шаги в /start)
ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN NOT NULL DEFAULT true;

-- настройки из панели /admin
CREATE TABLE IF NOT EXISTS app_settings (
  key VARCHAR(64) PRIMARY KEY,
  value JSONB NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

Точные имена колонок сверяйте с **`models/`** при изменениях кода.

---

## 11. Безопасность (перед продом)

- [ ] Секреты только в **`.env` / secrets**, не в git.
- [ ] HTTPS на домене с вебхуком ЮKassa.
- [ ] Ограничить доступ к порту 8080 файрволом (только прокси/ЮKassa).
- [ ] Рассмотреть **IP-диапазоны ЮKassa** для вебхука (документация ЮKassa).

---

## Связанные файлы

| Файл | Назначение |
|------|------------|
| `.env.example` | Шаблон переменных окружения |
| `документация/MVP-Product-Logic.md` | Продуктовая логика MVP |
| `документация/OpenClaw.md` | Исходное ТЗ / архитектура |
| `docker-compose.yml` | Postgres, Redis, бот + порт 8080 |

---

## FAQ: Gemma и Ollama — это не «или-или»

**Ollama** — это программа на вашем сервере/ПК, которая **запускает** локальные модели (API к ним).

**Gemma** — это **семейство моделей** от Google; многие варианты можно **поставить в Ollama** командой `ollama pull …` (актуальный список тегов смотрите на [ollama.com/library](https://ollama.com/library) или `ollama search gemma`).

Фраза «Gemma 4» может означать конкретную версию/релиз; на момент правки документа ориентируйтесь на то, что **реально есть в каталоге Ollama** (например Gemma 2 / Gemma 3 под разные размеры).

**Что выбрать для проекта**

- Нужна **скорость и мало RAM** — меньшие квантованные модели (маленький Gemma/Llama/Qwen в Ollama).
- Нужно **качество рассуждений** — крупнее модель и/или сильнее квант, больше памяти GPU/RAM.
- Сейчас в `.env` по умолчанию **`OLLAMA_MODEL=llama3.1:8b`** — разумный компромисс; **Gemma в Ollama** можно поставить параллельно и переключить только переменной **`OLLAMA_MODEL`**, без смены кода.

Итого: **не «Gemma вместо Ollama»**, а **«какую модель тянуть в Ollama»** — Gemma и Llama обе нормальны; сравните на ваших задачах и железе за 1–2 вечера тестов.
