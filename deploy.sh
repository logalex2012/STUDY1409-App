#!/usr/bin/env bash
set -euo pipefail

SERVER_USER="${DEPLOY_USER:-deploy}"
SERVER_HOST="student.my1409.ru"
SERVER_DIR="/var/www/study1409"
SERVICE_NAME="study1409"

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

rsync -avz --delete \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.env' \
  "${DIR}/" \
  "${SERVER_USER}@${SERVER_HOST}:${SERVER_DIR}/"

ssh "${SERVER_USER}@${SERVER_HOST}" \
  "sudo systemctl restart ${SERVICE_NAME} && sudo systemctl is-active ${SERVICE_NAME}"

echo "Done: https://${SERVER_HOST}"
