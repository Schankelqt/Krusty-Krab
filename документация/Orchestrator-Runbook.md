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

## 4) Быстрая диагностика по логам и событиям

Worker и provisioning-сервис пишут структурированные логи в формате
`<метка> key=value …`. Логи бота берутся из docker compose:

```bash
docker compose logs --since 1h bot
docker compose logs -f bot
```

### Ключевые лог-метки

Лайфцикл job:

| Метка | Когда | Что искать |
| --- | --- | --- |
| `provision_job queued` | новая job создана | `job_id`, `owner_user_id`, `template` |
| `provision_job reused` | сработала идемпотентность | повторный клик пользователя — это норма |
| `provision_worker loop_start` | worker-таск стартанул | один раз на запуск процесса |
| `provision_worker picked` | worker взял job из очереди | задача перешла `queued → running` |
| `provision_worker idle …` | очередь пуста / job не подобран | при DEBUG-уровне; если job залип — значит worker всё-таки тикает |
| `provision_step running` | шаг начат | первый шаг после `picked` должен быть `validate_input` |
| `provision_step completed` | шаг завершён | по 4 строки на успешную job |
| `provision_step failed` | шаг упал | `step=...`, `error=...` |
| `provision_job completed` | job дошёл до конца | `duration_ms` |
| `provision_job failed` | job упал | `step=...`, `error=...`, traceback ниже |
| `provision_worker tick failed` | необработанное исключение в loop | стек в `traceback`, worker сам не падает |

### Быстрые команды

Полный тайм-лайн конкретной job:

```bash
docker compose logs --since 24h bot | grep "job_id=42"
```

Все падения за час:

```bash
docker compose logs --since 1h bot | grep -E "provision_(job|step) failed"
```

Проверить, что worker реально тикает (не завис):

```bash
docker compose logs --since 5m bot | grep -E "provision_worker (picked|loop_start|tick failed)"
```

Если совсем подозрительно тихо — временно поднять уровень логов до DEBUG
(в `bot/main.py` `logging.basicConfig(level=...)`) и посмотреть `provision_worker idle`.

### События в `bot_events`

Под каждый ключевой переход worker/provisioning кидает запись через
`record_event(...)`. Эти события используются метриками и удобны для пост-мортем
без чтения логов:

- `provision_job_queued` — payload: `job_id`, `template_key`, `steps`
- `provision_job_running` — payload: `job_id`, `template_key`
- `provision_job_completed` — payload: `job_id`, `template_key`, `duration_ms`, `assistant_instance_id`
- `provision_job_failed` — payload: `job_id`, `template_key`, `step`, `duration_ms`, `error`

Лайфцикл одной job из БД:

```sql
select created_at, event_type, user_id, payload
from bot_events
where event_type like 'provision_job_%'
  and payload->>'job_id' = :job_id
order by created_at;
```

Сводка успехов/падений за сутки:

```sql
select event_type, count(*)
from bot_events
where event_type in (
    'provision_job_queued',
    'provision_job_running',
    'provision_job_completed',
    'provision_job_failed'
)
  and created_at >= now() - interval '24 hours'
group by event_type
order by event_type;
```

Топ ошибок за сутки:

```sql
select payload->>'step' as step,
       payload->>'error' as error,
       count(*) as n
from bot_events
where event_type = 'provision_job_failed'
  and created_at >= now() - interval '24 hours'
group by step, error
order by n desc
limit 20;
```

p50/p95 длительности завершённых job за сутки:

```sql
select percentile_disc(0.5) within group (order by (payload->>'duration_ms')::int) as p50_ms,
       percentile_disc(0.95) within group (order by (payload->>'duration_ms')::int) as p95_ms
from bot_events
where event_type = 'provision_job_completed'
  and created_at >= now() - interval '24 hours';
```

Зависшие в `running` дольше N секунд (без события `provision_job_completed`/`_failed`):

```sql
select pj.id, pj.owner_user_id, pj.status, pj.updated_at
from provision_jobs pj
where pj.status = 'running'
  and pj.updated_at < now() - interval '5 minutes'
order by pj.updated_at;
```
