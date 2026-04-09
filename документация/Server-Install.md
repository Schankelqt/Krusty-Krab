# Установка на сервер (Docker, OpenClaw Gateway, бот)

Один скрипт готовит **Ubuntu/Debian** VPS: ставит Docker, клонирует [OpenClaw](https://github.com/openclaw/openclaw), поднимает **Gateway** из образа **GHCR** (без сборки), опционально клонирует Krusty-Krab.

## Одной командой (рекомендуется)

После пуша репозитория в GitHub (подставьте свой `owner/repo` и ветку). Нужны **оба** скрипта в одной папке:

```bash
BASE="https://raw.githubusercontent.com/OWNER/Krusty-Krab/main/scripts"
curl -fsSL "$BASE/install-server.sh" -o /tmp/kk-install.sh
curl -fsSL "$BASE/openclaw-gateway-bootstrap.sh" -o /tmp/openclaw-gateway-bootstrap.sh
chmod +x /tmp/kk-install.sh /tmp/openclaw-gateway-bootstrap.sh
sudo BOOTSTRAP_SCRIPT=/tmp/openclaw-gateway-bootstrap.sh KRUSTY_REPO=https://github.com/OWNER/Krusty-Krab.git bash /tmp/kk-install.sh
```

Без `KRUSTY_REPO` скрипт поднимет только Docker и OpenClaw; репозиторий бота клонируйте отдельно.

Если репозиторий приватный — склонируйте Krusty-Krab на сервер и выполните из корня проекта (URL для клона бота подтянется из `git remote`):

```bash
sudo bash scripts/install-server.sh
```

Переменные (все опционально):

| Переменная | По умолчанию | Назначение |
|------------|--------------|------------|
| `OPENCLAW_ROOT` | `/opt/openclaw` | Каталог клона OpenClaw |
| `OPENCLAW_REPO` | `https://github.com/openclaw/openclaw.git` | Источник OpenClaw |
| `KRUSTY_ROOT` | `/opt/krusty-krab` | Куда клонировать бота |
| `KRUSTY_REPO` | авто из `git remote` при запуске из клона | URL репозитория бота |
| `SKIP_OPENCLAW=1` | — | Только Docker (+ опционально Krusty) |
| `SKIP_KRUSTY_CLONE=1` | — | Не клонировать бота |
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
sudo bash /path/to/Krusty-Krab/scripts/openclaw-gateway-bootstrap.sh /opt/openclaw
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

## HTTP OpenResponses

Бот ходит в Gateway по **`POST /v1/responses`**. Включите endpoint в конфигурации Gateway по [документации OpenResponses](https://docs.openclaw.ai/gateway/openresponses-http-api).

## Обновление OpenClaw

```bash
cd /opt/openclaw
git pull --ff-only
docker compose pull openclaw-gateway
docker compose up -d openclaw-gateway
```

## Безопасность

Не публикуйте порт `18789` в интернет без TLS и ограничения доступа. Для продакшена обычно используют reverse proxy (Caddy/NGINX) с HTTPS и firewall только для нужных IP.
