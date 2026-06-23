#!/usr/bin/env bash
set -e

SERVER_USER="${DEPLOY_USER:-deploy}"
SERVER_HOST="student.my1409.ru"
SERVER_PORT=59002
PROJECT_DIR="/opt/app/MY1409"

ssh -p "${SERVER_PORT}" "${SERVER_USER}@${SERVER_HOST}" "
cd ${PROJECT_DIR} || { echo 'Ошибка: Не удалось найти директорию ${PROJECT_DIR}. Прерываю выполнение.'; exit 1; }
git pull
docker-compose up -d --build --force-recreate
"

echo "Развертывание успешно завершено!"
