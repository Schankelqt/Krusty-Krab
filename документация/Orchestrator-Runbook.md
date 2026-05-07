# Orchestrator Runbook (MVP)

Короткая операционная памятка по orchestrator-потоку provisioning.

## 1) Как поставить тестовый job через Telegram

Минимальный сценарий:

1. Откройте диалог с ботом и выполните `/start`.
2. Запустите создание ассистента командой:
   - `/create_assistant тестовый ассистент для проверки`
3. Скопируйте `job_id` из ответа.
4. Проверьте статус:
   - `/jobs <job_id>`
5. Проверьте список созданных ассистентов:
   - `/my_assistants`

Ожидаемое поведение:
- сразу после запуска: `job_status=queued` или `running`;
- после выполнения: `job_status=completed`, ассистент в списке со статусом `ready`.

## 2) Быстрая проверка БД (SQL snippets)

Ниже запросы для Postgres, чтобы быстро увидеть состояние orchestrator-цепочки.

Последние job:

```sql
select id,
       owner_user_id,
       assistant_instance_id,
       status,
       created_at,
       updated_at,
       finished_at
from provision_jobs
order by created_at desc
limit 20;
```

Шаги конкретного job:

```sql
select job_id,
       step_key,
       status,
       attempt,
       started_at,
       finished_at,
       details_json
from provision_steps
where job_id = :job_id
order by started_at asc, id asc;
```

Ассистенты пользователя:

```sql
select id,
       owner_user_id,
       title,
       template_key,
       status,
       created_at,
       updated_at
from assistant_instances
where owner_user_id = :owner_user_id
order by created_at desc;
```

Связка job <-> ассистент:

```sql
select j.id as job_id,
       j.status as job_status,
       a.id as assistant_id,
       a.status as assistant_status,
       j.updated_at
from provision_jobs j
join assistant_instances a on a.id = j.assistant_instance_id
order by j.created_at desc
limit 20;
```

## 3) Статусы и базовый troubleshooting

### Ожидаемые статусы `provision_jobs`

- `queued` — задача создана и ждёт worker.
- `running` — worker выполняет шаги.
- `needs_input` — нужна дополнительная информация/подтверждение от пользователя.
- `failed` — job завершился ошибкой.
- `completed` — provisioning завершён успешно.

### Что проверять в первую очередь

- Job застрял в `queued`:
  - проверить, что worker-процесс запущен и читает очередь;
  - проверить подключение к Postgres/Redis.
- Job застрял в `running`:
  - открыть `provision_steps` и найти последний `step_key`;
  - проверить `details_json` и логи worker по `job_id`.
- Job в `failed`:
  - взять `error_message` из `provision_jobs`;
  - проверить последний неуспешный шаг в `provision_steps`;
  - перезапустить provisioning новой командой `/create_assistant` (новая job, без перезаписи истории).
- Job в `needs_input`:
  - запросить у пользователя недостающие данные;
  - после получения данных вернуть job в `running` через штатный обработчик.

### Признак «всё хорошо»

- `provision_jobs.status=completed`;
- связанный `assistant_instances.status=ready`;
- `/my_assistants` показывает нового ассистента.
