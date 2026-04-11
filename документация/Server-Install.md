# Установка на сервер (Docker, OpenClaw Gateway, бот)

Один скрипт готовит **Ubuntu/Debian** VPS: ставит Docker, клонирует [OpenClaw](https://github.com/openclaw/openclaw), поднимает **Gateway** из образа **GHCR** (без сборки), опционально клонирует репозиторий бота **Clawd**.

## Одной командой (рекомендуется)

После пуша репозитория в GitHub (подставьте свой `owner/repo` и ветку). Нужны **оба** скрипта в одной папке:

```bash
BASE="https://raw.githubusercontent.com/OWNER/Clawd/main/scripts"
curl -fsSL "$BASE/install-server.sh" -o /tmp/clawd-install.sh
curl -fsSL "$BASE/openclaw-gateway-bootstrap.sh" -o /tmp/openclaw-gateway-bootstrap.sh
chmod +x /tmp/clawd-install.sh /tmp/openclaw-gateway-bootstrap.sh
sudo BOOTSTRAP_SCRIPT=/tmp/openclaw-gateway-bootstrap.sh CLAWD_REPO=https://github.com/OWNER/Clawd.git bash /tmp/clawd-install.sh
```

Без `CLAWD_REPO` (или устаревшего `KRUSTY_REPO`) скрипт поднимет только Docker и OpenClaw; репозиторий бота клонируйте отдельно.

Если репозиторий приватный — склонируйте Clawd на сервер и выполните из корня проекта (URL для клона бота подтянется из `git remote`):

```bash
sudo bash scripts/install-server.sh
```

Переменные (все опционально):

| Переменная | По умолчанию | Назначение |
|------------|--------------|------------|
| `OPENCLAW_ROOT` | `/opt/openclaw` | Каталог клона OpenClaw |
| `OPENCLAW_REPO` | `https://github.com/openclaw/openclaw.git` | Источник OpenClaw |
| `CLAWD_ROOT` | `/opt/clawd` | Куда клонировать бота (`KRUSTY_ROOT` — устаревший алиас) |
| `CLAWD_REPO` / `KRUSTY_REPO` | авто из `git remote` при запуске из клона | URL репозитория бота |
| `SKIP_OPENCLAW=1` | — | Только Docker (+ опционально бот) |
| `SKIP_CLAWD_CLONE=1` / `SKIP_KRUSTY_CLONE=1` | — | Не клонировать бота |
| `OPENCLAW_CONFIG_DIR` | `/opt/openclaw-data/config` при `install-server` | Данные Gateway |
| `OPENCLAW_WORKSPACE_DIR` | `/opt/openclaw-data/workspace` | Workspace Gateway |

После скрипта в консоли будет **токен Gateway** — его копируете в `.env` бота как **`OPENCLAW_API_KEY`** (Bearer для `POST /v1/responses`).

## Только OpenClaw (уже есть Docker)

```bash
git clone --depth 1 https://github.com/openclaw/openclaw.git /opt/openclaw
export OPENCLAW_IMAGE=ghcr.io/openclaw/openclaw:latest
export OPENCLAW_CONFIG_DIR=/opt/openclaw-data/config
export OPENCLAW_WORKSPACE_DIR=/opt/openclaw-data/workspace
sudo mkdir -p "$OPENCLAW_CONFIG_DIR" "$OPENCLAW_WORKSPACE_DIR"
sudo chown -R 1000:1000 "$OPENCLAW_CONFIG_DIR" "$OPENCLAW_WORKSPACE_DIR"
sudo bash /path/to/Clawd/scripts/openclaw-gateway-bootstrap.sh /opt/openclaw
```

Официальный интерактивный путь (мастер с вопросами по провайдерам):

```bash
cd /opt/openclaw
export OPENCLAW_IMAGE=ghcr.io/openclaw/openclaw:latest
./scripts/docker/setup.sh
```

Документация OpenClaw по Docker: [docs.openclaw.ai — Docker](https://docs.openclaw.ai/install/docker).

## Связка бот ↔ OpenClaw на одном хосте

В `docker-compose.yml` у сервиса `bot` задано `extra_hosts: host.docker.internal:host-gateway`, чтобы из контейнера достучаться до Gateway на хосте.

В `.env` бота:

```env
PRIMARY_PROVIDER=openclaw
OPENCLAW_URL=http://host.docker.internal:18789
OPENCLAW_API_KEY=<OPENCLAW_GATEWAY_TOKEN из вывода скрипта или из .env OpenClaw>
```

Проверка с хоста:

```bash
curl -fsS http://127.0.0.1:18789/healthz
```

## Ollama рядом с ботом (Docker Compose)

Чтобы триал/фолбэк шли в локальную модель без установки Ollama на хост вручную:

```bash
docker compose --env-file .env --profile ollama up -d --build
```

В `.env` бота укажите `OLLAMA_BASE_URL=http://ollama:11434`, `TRIAL_PROVIDER=ollama`, `FALLBACK_PROVIDER=ollama`, модель — `OLLAMA_MODEL` (после первого старта: `docker compose exec ollama ollama pull <имя>`).

**Связка OpenClaw → Ollama:** модель и провайдер задаются в конфигурации **OpenClaw Gateway** (веб-UI или CLI после `onboard`): укажите там Ollama как бэкенд (хост `host.docker.internal:11434`, если Ollama в compose на том же сервере, либо имя сервиса `ollama`, если Gateway тоже в общей Docker-сети — зависит от того, как вы подняли Gateway). Бот к LLM ходит только через свой роутер (`openclaw` / `openai` / …); OpenClaw сам проксирует запросы к выбранному вами бэкенду.

## HTTP OpenResponses

Бот ходит в Gateway по **`POST /v1/responses`**. Скрипт `scripts/openclaw-gateway-bootstrap.sh` включает `gateway.http.endpoints.responses.enabled` и режим `gateway.auth.mode=token`. Подробности: [документация OpenResponses](https://docs.openclaw.ai/gateway/openresponses-http-api).

## Обновление OpenClaw

```bash
cd /opt/openclaw
git pull --ff-only
docker compose pull openclaw-gateway
docker compose up -d openclaw-gateway
```

## Безопасность

Не публикуйте порт `18789` в интернет без TLS и ограничения доступа. Для продакшена обычно используют reverse proxy (Caddy/NGINX) с HTTPS и firewall только для нужных IP.
