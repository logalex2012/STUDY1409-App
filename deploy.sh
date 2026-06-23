#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════
#  deploy.sh — Деплой STUDY1409 на student.my1409.ru
#
#  Что делает:
#  1. Подменяет API_BASE в login.html  (dev → prod)
#  2. Синхронизирует файлы на сервер   (rsync)
#  3. Перезапускает сервис             (systemctl)
#  4. Откатывает API_BASE локально     (возврат к dev)
# ══════════════════════════════════════════════════════════
set -euo pipefail

# ── Конфигурация ──────────────────────────────────────────
SERVER_USER="${DEPLOY_USER:-deploy}"
SERVER_HOST="student.my1409.ru"
SERVER_DIR="/var/www/study1409"
SERVICE_NAME="study1409"          # systemctl service

# URL в коде
DEV_BASE="http://127.0.0.1:1409"
PROD_BASE="my1409.ru"                       # пустая строка = относительные URL

# ── Цвета для вывода ──────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}▸ $*${RESET}"; }
success() { echo -e "${GREEN}✓ $*${RESET}"; }
warn()    { echo -e "${YELLOW}! $*${RESET}"; }
die()     { echo -e "${RED}✗ $*${RESET}" >&2; exit 1; }

echo -e "\n${BOLD}═══════════════════════════════════════${RESET}"
echo -e "${BOLD}  STUDY1409 — Deploy → ${SERVER_HOST}${RESET}"
echo -e "${BOLD}═══════════════════════════════════════${RESET}\n"

# ── 0. Проверки ───────────────────────────────────────────
command -v rsync >/dev/null 2>&1 || die "rsync не найден"
command -v ssh   >/dev/null 2>&1 || die "ssh не найден"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGIN_HTML="${SCRIPT_DIR}/login.html"

[[ -f "${LOGIN_HTML}" ]] || die "login.html не найден: ${LOGIN_HTML}"

# ── 1. Подмена API_BASE (dev → prod) ─────────────────────
info "Подменяем API_BASE: '${DEV_BASE}' → '${PROD_BASE}'"

# Создаём backup для отката
cp "${LOGIN_HTML}" "${LOGIN_HTML}.deploy_bak"

# Замена в файле (работает и на macOS, и на Linux)
if [[ "$(uname)" == "Darwin" ]]; then
  sed -i '' \
    "s|const API_BASE = '${DEV_BASE}'|const API_BASE = '${PROD_BASE}'|g" \
    "${LOGIN_HTML}"
else
  sed -i \
    "s|const API_BASE = '${DEV_BASE}'|const API_BASE = '${PROD_BASE}'|g" \
    "${LOGIN_HTML}"
fi

# Проверяем, что замена сработала
if grep -q "API_BASE = '${DEV_BASE}'" "${LOGIN_HTML}"; then
  cp "${LOGIN_HTML}.deploy_bak" "${LOGIN_HTML}"
  die "Не удалось заменить API_BASE в login.html"
fi
success "API_BASE заменён"

# ── 2. Rsync файлов на сервер ─────────────────────────────
info "Отправляем файлы на ${SERVER_USER}@${SERVER_HOST}:${SERVER_DIR}"

rsync -avz --progress \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.env' \
  --exclude='maintenance.lock' \
  --exclude='*.deploy_bak' \
  --exclude='deploy.sh' \
  "${SCRIPT_DIR}/" \
  "${SERVER_USER}@${SERVER_HOST}:${SERVER_DIR}/"

success "Файлы загружены"

# ── 3. Перезапуск сервиса ─────────────────────────────────
info "Перезапускаем сервис ${SERVICE_NAME}…"

ssh "${SERVER_USER}@${SERVER_HOST}" \
  "sudo systemctl restart ${SERVICE_NAME} && sudo systemctl is-active ${SERVICE_NAME}"

success "Сервис перезапущен"

# ── 4. Откат API_BASE локально (dev-режим) ───────────────
info "Возвращаем локальный API_BASE к dev: '${DEV_BASE}'"
cp "${LOGIN_HTML}.deploy_bak" "${LOGIN_HTML}"
rm  "${LOGIN_HTML}.deploy_bak"
success "Локальный файл восстановлен"

# ── Done ──────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}══════════════════════════════════════════${RESET}"
echo -e "${GREEN}${BOLD}  Деплой завершён!  https://${SERVER_HOST}  ${RESET}"
echo -e "${GREEN}${BOLD}══════════════════════════════════════════${RESET}"
echo ""
