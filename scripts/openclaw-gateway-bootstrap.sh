#!/usr/bin/env bash
# Запускать с корня клонированного репозитория OpenClaw (рядом с docker-compose.yml).
# Поднимает Gateway из готового образа GHCR, без локальной сборки.
# Первичный onboard — неинтерактивный (--auth-choice skip); провайдеры настраиваются
# позже в UI Gateway или через openclaw-cli (см. документацию OpenClaw).
set -euo pipefail

OPENCLAW_ROOT="${1:-${OPENCLAW_ROOT:-.}}"
OPENCLAW_ROOT="$(cd "$OPENCLAW_ROOT" && pwd)"

if [[ ! -f "$OPENCLAW_ROOT/docker-compose.yml" ]]; then
  echo "ERROR: В $OPENCLAW_ROOT нет docker-compose.yml (нужен клон github.com/openclaw/openclaw)." >&2
  exit 1
fi

export OPENCLAW_IMAGE="${OPENCLAW_IMAGE:-ghcr.io/openclaw/openclaw:latest}"
export OPENCLAW_GATEWAY_PORT="${OPENCLAW_GATEWAY_PORT:-18789}"
export OPENCLAW_GATEWAY_BIND="${OPENCLAW_GATEWAY_BIND:-lan}"
export OPENCLAW_CONFIG_DIR="${OPENCLAW_CONFIG_DIR:-$HOME/.openclaw}"
export OPENCLAW_WORKSPACE_DIR="${OPENCLAW_WORKSPACE_DIR:-$HOME/.openclaw/workspace}"

if [[ -z "${OPENCLAW_GATEWAY_TOKEN:-}" ]]; then
  if command -v openssl >/dev/null 2>&1; then
    export OPENCLAW_GATEWAY_TOKEN="$(openssl rand -hex 32)"
  else
    export OPENCLAW_GATEWAY_TOKEN="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  fi
fi

mkdir -p "$OPENCLAW_CONFIG_DIR/identity" \
  "$OPENCLAW_CONFIG_DIR/agents/main/agent" \
  "$OPENCLAW_CONFIG_DIR/agents/main/sessions" \
  "$OPENCLAW_WORKSPACE_DIR"

# Права для пользователя node (uid 1000) внутри контейнера
if [[ "$(id -u)" -eq 0 ]]; then
  chown -R 1000:1000 "$OPENCLAW_CONFIG_DIR" "$OPENCLAW_WORKSPACE_DIR" 2>/dev/null || true
fi

cd "$OPENCLAW_ROOT"

# Синхронизируем .env в корне OpenClaw для docker compose
ENV_FILE="$OPENCLAW_ROOT/.env"
upsert_kv() {
  local key="$1" val="$2" f="$ENV_FILE"
  if [[ -f "$f" ]] && grep -q "^${key}=" "$f" 2>/dev/null; then
    if [[ "$(uname -s)" == "Darwin" ]]; then
      sed -i '' "s|^${key}=.*|${key}=${val}|" "$f"
    else
      sed -i "s|^${key}=.*|${key}=${val}|" "$f"
    fi
  else
    printf '%s=%s\n' "$key" "$val" >>"$f"
  fi
}

touch "$ENV_FILE"
upsert_kv OPENCLAW_IMAGE "$OPENCLAW_IMAGE"
upsert_kv OPENCLAW_CONFIG_DIR "$OPENCLAW_CONFIG_DIR"
upsert_kv OPENCLAW_WORKSPACE_DIR "$OPENCLAW_WORKSPACE_DIR"
upsert_kv OPENCLAW_GATEWAY_TOKEN "$OPENCLAW_GATEWAY_TOKEN"
upsert_kv OPENCLAW_GATEWAY_PORT "$OPENCLAW_GATEWAY_PORT"
upsert_kv OPENCLAW_GATEWAY_BIND "$OPENCLAW_GATEWAY_BIND"

echo "==> Pull образа $OPENCLAW_IMAGE"
docker compose pull openclaw-gateway

echo "==> Права на каталоги конфигурации (контейнер от root)"
docker compose run --rm --no-deps --user root --entrypoint sh openclaw-gateway -c \
  'find /home/node/.openclaw -xdev -exec chown node:node {} + 2>/dev/null; true'

echo "==> Onboard (non-interactive, провайдеры — skip; добавьте ключи в UI или CLI позже)"
set +e
docker compose run --rm --no-deps --entrypoint node openclaw-gateway \
  dist/index.js onboard --mode local --no-install-daemon \
  --non-interactive --accept-risk --auth-choice skip --skip-channels
onboard_rc=$?
set -e
if [[ "$onboard_rc" -ne 0 ]]; then
  echo "WARN: Неинтерактивный onboard завершился с кодом $onboard_rc." >&2
  echo "      Запустите вручную из $OPENCLAW_ROOT:" >&2
  echo "      OPENCLAW_IMAGE=$OPENCLAW_IMAGE ./scripts/docker/setup.sh" >&2
fi

echo "==> Базовые параметры gateway (local + lan)"
docker compose run --rm --no-deps --entrypoint node openclaw-gateway \
  dist/index.js config set --batch-json \
  "[{\"path\":\"gateway.mode\",\"value\":\"local\"},{\"path\":\"gateway.bind\",\"value\":\"${OPENCLAW_GATEWAY_BIND}\"},{\"path\":\"gateway.controlUi.allowedOrigins\",\"value\":[\"http://localhost:${OPENCLAW_GATEWAY_PORT}\",\"http://127.0.0.1:${OPENCLAW_GATEWAY_PORT}\"]}]" \
  >/dev/null 2>&1 || true

echo "==> HTTP OpenResponses (POST /v1/responses) + shared-secret auth для бота"
GATEWAY_HTTP_JSON="$(
  OPENCLAW_GATEWAY_TOKEN="$OPENCLAW_GATEWAY_TOKEN" python3 -c '
import json, os
t = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "")
print(json.dumps([
  {"path": "gateway.http.endpoints.responses.enabled", "value": True},
  {"path": "gateway.auth.mode", "value": "token"},
  {"path": "gateway.auth.token", "value": t},
]))
'
)"
docker compose run --rm --no-deps --entrypoint node openclaw-gateway \
  dist/index.js config set --batch-json "$GATEWAY_HTTP_JSON" \
  >/dev/null 2>&1 || true

echo "==> Старт openclaw-gateway"
docker compose up -d openclaw-gateway

echo ""
echo "Gateway: http://127.0.0.1:${OPENCLAW_GATEWAY_PORT}/"
echo "Токен (Bearer → OPENCLAW_API_KEY в .env бота Clawd): ${OPENCLAW_GATEWAY_TOKEN}"
echo "В .env бота: OPENCLAW_URL=http://host.docker.internal:${OPENCLAW_GATEWAY_PORT}"
echo "Проверка: curl -fsS -H \"Authorization: Bearer \${OPENCLAW_GATEWAY_TOKEN}\" http://127.0.0.1:${OPENCLAW_GATEWAY_PORT}/v1/models"
echo "Модель/бэкенд LLM в Gateway настраивается в UI или CLI OpenClaw (Ollama, облачные API и т.д.)."
