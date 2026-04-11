# Clawd — Telegram SaaS-бот с подпиской и сеткой моделей

Персональный AI-ассистент в Telegram: триал, мягкий режим после триала, оплата через ЮKassa, пакеты токенов по линиям **GPT / Claude / Gemini**, лимиты и метрики.

## Быстрый старт

1. Скопируйте окружение: `cp .env.example .env` и заполните `BOT_TOKEN`, `DATABASE_URL`, `REDIS_URL`.
2. Поднимите инфраструктуру: `docker compose --env-file .env up -d --build`.
3. Укажите в `.env` `ADMIN_IDS` (ваш Telegram user id) и при внутреннем тесте — `INTERNAL_WHITELIST_IDS`.
4. Команда **`/admin`** — панель настроек (лимиты, уведомления, whitelist без деплоя).

Подробный чеклист: [`документация/Setup-Guide.md`](документация/Setup-Guide.md). Продуктовая логика: [`документация/MVP-Product-Logic.md`](документация/MVP-Product-Logic.md).  
Установка на VPS с Docker и **OpenClaw Gateway**: [`документация/Server-Install.md`](документация/Server-Install.md) (`sudo bash scripts/install-server.sh`). Профиль **Ollama** в `docker compose`: `--profile ollama`.

## Возможности

- Онбординг для новых пользователей (шаги с inline-кнопками).
- Админ-панель в Telegram: лимиты триала/soft/fallback, напоминания клиентам о конце периода, флаги алертов команде.
- Уведомления команде: новый пользователь, успешная оплата, необработанные ошибки (настраивается в панели).
- Напоминание клиенту за N дней до окончания подписки (фоновая задача, раз в час).

## Стек

Python 3.11+, aiogram 3, FastAPI (вебхук ЮKassa), PostgreSQL, Redis, SQLAlchemy 2 async.
