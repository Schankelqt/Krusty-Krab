#!/usr/bin/env bash
# Подключить OpenClaw Gateway (Docker) к Ollama на хосте.
# По умолчанию Ollama слушает 127.0.0.1:11434 (см. docker-compose бота); из контейнера
# Gateway достучаться можно через IP docker0 на хосте (часто 172.17.0.1).
#
# Перед запуском: поднимите Ollama и сделайте pull модели, например:
#   docker compose --env-file .env --profile ollama up -d
#   bash scripts/ollama-pull-default.sh
#
# Переменные:
#   OPENCLAW_ROOT=/opt/openclaw
#   OLLAMA_URL=http://172.17.0.1:11434   — URL с точки зрения контейнера gateway
#   OLLAMA_MODEL=qwen2.5:0.5b
set -euo pipefail

OPENCLAW_ROOT="${OPENCLAW_ROOT:-/opt/openclaw}"
OLLAMA_URL="${OLLAMA_URL:-http://172.17.0.1:11434}"
MODEL="${OLLAMA_MODEL:-qwen2.5:0.5b}"

if [[ ! -f "$OPENCLAW_ROOT/docker-compose.yml" ]]; then
  echo "ERROR: не найден $OPENCLAW_ROOT/docker-compose.yml" >&2
  exit 1
fi

cd "$OPENCLAW_ROOT"
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source ./.env
  set +a
fi

echo "==> OpenClaw onboard: Ollama $OLLAMA_URL, модель $MODEL"
# --skip-health: в одноразовом контейнере нет запущенного gateway на 127.0.0.1:18789 — без флага onboard падает после успешного обновления конфига.
set +e
docker compose run --rm --no-deps --entrypoint node openclaw-gateway \
  dist/index.js onboard --non-interactive --auth-choice ollama \
  --custom-base-url "$OLLAMA_URL" \
  --custom-model-id "$MODEL" \
  --accept-risk --skip-channels --skip-health
onboard_rc=$?
set -e
if [[ "$onboard_rc" -ne 0 ]]; then
  echo "WARN: onboard exit $onboard_rc — если выше было «Config overwrite» / «Default Ollama model», конфиг уже применён." >&2
fi

echo "==> Перезапуск openclaw-gateway (подхватить openclaw.json)"
docker compose up -d openclaw-gateway
echo "==> Перезапущен openclaw-gateway. Проверка с хоста:"
echo "    curl -fsS -H \"Authorization: Bearer \$OPENCLAW_GATEWAY_TOKEN\" http://127.0.0.1:18789/v1/models"
