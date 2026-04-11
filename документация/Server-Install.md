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

Лёгкая модель по умолчанию в шаблоне: **`qwen2.5:0.5b`** (мало RAM/диска; не облачный API — локальный инференс).

```bash
cd /opt/krusty-krab   # или каталог бота
docker compose --env-file .env --profile ollama up -d --build
bash scripts/ollama-pull-default.sh
```

В `.env` бота для триала/фолбэка через Ollama: `OLLAMA_BASE_URL=http://ollama:11434`, `OLLAMA_MODEL=qwen2.5:0.5b`, `TRIAL_PROVIDER=ollama`, `FALLBACK_PROVIDER=ollama`, затем `docker compose --env-file .env --profile ollama up -d`.

### OpenClaw (в Docker) → Ollama на том же хосте

Gateway в отдельном compose не видит сервис `ollama` по имени. С хоста Ollama доступен на `127.0.0.1:11434`; **из контейнера** `openclaw-gateway` обычно подходит **`http://172.17.0.1:11434`** (интерфейс `docker0` на хосте). Если не коннектится, уточните IP: `ip -4 addr show docker0`.

Скрипт из репозитория бота (после `pull` модели):

```bash
sudo bash /opt/krusty-krab/scripts/openclaw-wire-ollama.sh
# или: OLLAMA_URL=http://172.17.0.1:11434 OLLAMA_MODEL=qwen2.5:0.5b OPENCLAW_ROOT=/opt/openclaw bash scripts/openclaw-wire-ollama.sh
```

Он запускает неинтерактивный `onboard` с провайдером Ollama и перезапускает gateway. Подробности и ручная настройка: [OpenClaw — Ollama](https://docs.openclaw.ai/providers/ollama) (нативный URL **без** суффикса `/v1`).

**Безопасность:** порт **11434** не должен быть открыт в интернет; ограничьте firewall-ом.

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

Не публикуйте порт `18789` в интернет без TLS и ограничения доступа. Для продакшена обычно используют reverse proxy (Caddy/NGINX) с HTTPS и firewall только для нужных IP. Порт **Ollama 11434** также держите только для локальной сети/localhost.
