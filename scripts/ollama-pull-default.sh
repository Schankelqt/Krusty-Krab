#!/usr/bin/env bash
# Скачать лёгкую модель в сервис ollama (профиль ollama в docker compose).
# Запуск из корня репозитория бота: bash scripts/ollama-pull-default.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
MODEL="${OLLAMA_MODEL:-qwen2.5:0.5b}"
echo "==> ollama pull $MODEL (нужен запущенный сервис ollama с профилем ollama)"
docker compose --profile ollama exec ollama ollama pull "$MODEL"
echo "==> Готово: docker compose --profile ollama exec ollama ollama list"
