#!/usr/bin/env bash
set -e

PROJECT_DIR="/root/app-pwa/STUDY1409-App"

cd "${PROJECT_DIR}" || { echo "Ошибка: Не удалось найти директорию ${PROJECT_DIR}."; exit 1; }

echo "--- Обновляю код из Git ---"
git pull

echo "--- Настраиваю nginx ---"
cp "${PROJECT_DIR}/nginx-study1409.conf" /etc/nginx/sites-available/study1409
ln -sf /etc/nginx/sites-available/study1409 /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

echo "--- Развертывание успешно завершено! ---"
