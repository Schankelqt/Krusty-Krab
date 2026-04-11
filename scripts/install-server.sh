#!/usr/bin/env bash
# Полная подготовка VPS (Ubuntu/Debian): Docker, клон OpenClaw, bootstrap Gateway,
# опционально клон репозитория бота (Clawd) и подсказки по .env.
#
# Запуск: sudo bash scripts/install-server.sh
# Или из уже клонированного Clawd: sudo bash ./scripts/install-server.sh
#
# Переменные окружения:
#   OPENCLAW_ROOT=/opt/openclaw
#   OPENCLAW_REPO=https://github.com/openclaw/openclaw.git
#   CLAWD_REPO / KRUSTY_REPO — URL git бота (клон в CLAWD_ROOT или KRUSTY_ROOT)
#   CLAWD_ROOT=/opt/clawd  (устаревшее имя: KRUSTY_ROOT)
#   SKIP_OPENCLAW=1  — только Docker + опционально клон бота
#   SKIP_KRUSTY_CLONE=1 / SKIP_CLAWD_CLONE=1 — не клонировать бота
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Корень репозитория бота, если скрипт лежит в scripts/
REPO_ROOT=""
if [[ -f "$SCRIPT_DIR/../docker-compose.yml" && -f "$SCRIPT_DIR/../bot/main.py" ]]; then
  REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

BOOTSTRAP_SCRIPT="${BOOTSTRAP_SCRIPT:-$SCRIPT_DIR/openclaw-gateway-bootstrap.sh}"

OPENCLAW_ROOT="${OPENCLAW_ROOT:-/opt/openclaw}"
OPENCLAW_REPO="${OPENCLAW_REPO:-https://github.com/openclaw/openclaw.git}"
CLAWD_ROOT="${CLAWD_ROOT:-${KRUSTY_ROOT:-/opt/clawd}}"
CLAWD_REPO="${CLAWD_REPO:-${KRUSTY_REPO:-}}"
SKIP_CLAWD_CLONE="${SKIP_CLAWD_CLONE:-${SKIP_KRUSTY_CLONE:-}}"

if [[ "${SKIP_OPENCLAW:-0}" != "1" && "${SKIP_CLAWD_CLONE:-0}" != "1" && -z "$CLAWD_REPO" && -n "$REPO_ROOT" ]]; then
  if git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    CLAWD_REPO="$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null || true)"
  fi
fi

die() { echo "ERROR: $*" >&2; exit 1; }

if [[ "$(id -u)" -ne 0 ]]; then
  die "Запустите от root или через sudo: sudo bash $0"
fi

if [[ "${SKIP_OPENCLAW:-0}" != "1" && ! -f "$BOOTSTRAP_SCRIPT" ]]; then
  die "Не найден openclaw-gateway-bootstrap.sh (ожидался: $BOOTSTRAP_SCRIPT).
Склонируйте репозиторий и выполните: sudo bash scripts/install-server.sh
или скачайте оба скрипта в одну папку и укажите BOOTSTRAP_SCRIPT=/путь/openclaw-gateway-bootstrap.sh"
fi

export DEBIAN_FRONTEND=noninteractive
apt_get() {
  apt-get update -qq
  apt-get install -y -qq "$@"
}

if ! command -v docker >/dev/null 2>&1; then
  echo "==> Установка Docker (официальный скрипт get.docker.com)"
  apt_get ca-certificates curl git python3
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker || true
else
  echo "==> Docker уже установлен"
  apt_get ca-certificates curl git python3 || true
fi

if [[ "${SKIP_OPENCLAW:-0}" != "1" ]]; then
  echo "==> Клон OpenClaw → $OPENCLAW_ROOT"
  if [[ -d "$OPENCLAW_ROOT/.git" ]]; then
    git -C "$OPENCLAW_ROOT" pull --ff-only || true
  else
    mkdir -p "$(dirname "$OPENCLAW_ROOT")"
    rm -rf "$OPENCLAW_ROOT"
    git clone --depth 1 "$OPENCLAW_REPO" "$OPENCLAW_ROOT"
  fi
fi

if [[ "${SKIP_OPENCLAW:-0}" != "1" ]]; then
  echo "==> Bootstrap OpenClaw Gateway"
  export OPENCLAW_CONFIG_DIR="${OPENCLAW_CONFIG_DIR:-/opt/openclaw-data/config}"
  export OPENCLAW_WORKSPACE_DIR="${OPENCLAW_WORKSPACE_DIR:-/opt/openclaw-data/workspace}"
  mkdir -p "$OPENCLAW_CONFIG_DIR" "$OPENCLAW_WORKSPACE_DIR"
  chown -R 1000:1000 "$OPENCLAW_CONFIG_DIR" "$OPENCLAW_WORKSPACE_DIR" 2>/dev/null || true
  bash "$BOOTSTRAP_SCRIPT" "$OPENCLAW_ROOT"
fi

if [[ "${SKIP_CLAWD_CLONE:-0}" != "1" && -n "$CLAWD_REPO" ]]; then
  echo "==> Клон бота (Clawd) → $CLAWD_ROOT"
  if [[ -d "$CLAWD_ROOT/.git" ]]; then
    git -C "$CLAWD_ROOT" pull --ff-only || true
  else
    mkdir -p "$(dirname "$CLAWD_ROOT")"
    rm -rf "$CLAWD_ROOT"
    git clone --depth 1 "$CLAWD_REPO" "$CLAWD_ROOT"
  fi
  echo "==> Шаблон .env"
  if [[ ! -f "$CLAWD_ROOT/.env" ]]; then
    cp "$CLAWD_ROOT/.env.example" "$CLAWD_ROOT/.env" || true
  fi
  echo ""
  echo "--- Дальше в $CLAWD_ROOT/.env заполните BOT_TOKEN, DATABASE_URL, REDIS_URL, ключи ЮKassa и т.д."
  echo "--- Для Docker-сборки бота укажите (OpenClaw на том же хосте):"
  echo "    PRIMARY_PROVIDER=openclaw"
  echo "    OPENCLAW_URL=http://host.docker.internal:18789"
  echo "    OPENCLAW_API_KEY=<тот же токен, что вывел скрипт OpenClaw>"
  echo "--- Ollama на этом же хосте: docker compose --profile ollama; в .env бота OLLAMA_BASE_URL=http://ollama:11434"
  echo "--- Запуск: cd $CLAWD_ROOT && docker compose --env-file .env up -d --build"
elif [[ -n "$REPO_ROOT" && -f "$REPO_ROOT/docker-compose.yml" ]]; then
  echo ""
  echo "--- Текущий репозиторий: $REPO_ROOT"
  echo "--- Скопируйте OPENCLAW_API_KEY из вывода OpenClaw в .env и задайте OPENCLAW_URL=http://host.docker.internal:18789"
fi

echo ""
echo "Готово."
