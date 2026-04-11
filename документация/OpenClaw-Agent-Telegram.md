# OpenClaw: Gateway и персонализация из Telegram

## Gateway (сервер)

1. Поднять OpenClaw Gateway с включённым **`POST /v1/responses`** (см. `scripts/openclaw-gateway-bootstrap.sh`, [OpenResponses API](https://docs.openclaw.ai/gateway/openresponses-http-api)).
2. В `.env` бота: **`OPENCLAW_URL`**, **`OPENCLAW_API_KEY`**, при необходимости **`OPENCLAW_MODEL`**, **`OPENCLAW_AGENT_ID`**.
3. В Gateway настроить **бэкенд LLM** (Ollama, облако и т.д.) — это отдельно от кода бота; бот шлёт только текст в `input`.

## Персонализация (бот → Gateway)

- В таблице **`users`**: `agent_display_name`, `agent_instructions` (см. `scripts/sql/add_agent_personalization.sql` для существующей БД).
- При каждом запросе к OpenClaw поле **`input`** собирается так: префикс с именем и инструкциями + «Сообщение пользователя» + текст из чата (`services/openclaw_input.py`).
- Отдельного поля `system` в HTTP API не используется — всё в одном `input`, как ожидает текущий клиент.

## Сессия OpenClaw

- Ключ сессии: **`openclaw_session_id`** в БД; если пусто — используется `telegram-{user_id}`.
- Кнопка **«Новый диалог»** в настройках задаёт новый ключ `telegram-{id}-{hex}` — история в Gateway начинается заново.

## Telegram UX

- Кнопка **`BTN_AGENT_SETTINGS`** (по умолчанию «⚙️ Настройки ассистента») или команда **`/agent`**.
- Inline-меню: имя, инструкции, сброс полей, новая сессия. Ввод текста — следующим сообщением; **`/cancel`** в режиме ввода.

## Ограничения текущей версии

- Персонализация влияет только на провайдер **`openclaw`** (поле `input`).
- Прямые вызовы OpenAI / Anthropic / Gemini из бота инструкции пользователя **не** подмешивают (отдельная задача).
- Биллинг и лимиты на облачный LLM через Gateway — по плану «позже», без изменений в этом документе.
