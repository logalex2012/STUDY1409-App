#!/usr/bin/env bash
set -e

PROJECT_DIR="/root/app-pwa/STUDY1409-App"

cd "${PROJECT_DIR}" || { echo "Ошибка: Не удалось найти директорию ${PROJECT_DIR}."; exit 1; }

echo "--- Обновляю код из Git ---"
git pull

echo "--- Устанавливаю/обновляю зависимости ---"
pip3 install -r "${PROJECT_DIR}/requirements.txt"

echo "--- Настраиваю systemd-сервис (Flask работает 24/7) ---"
cp "${PROJECT_DIR}/study1409-app.service" /etc/systemd/system/study1409-app.service
systemctl daemon-reload
systemctl enable study1409-app.service
systemctl restart study1409-app.service

echo "--- Настраиваю nginx ---"
cp "${PROJECT_DIR}/nginx-study1409.conf" /etc/nginx/sites-available/study1409
ln -sf /etc/nginx/sites-available/study1409 /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx || systemctl start nginx

echo "--- Развертывание успешно завершено! ---"
systemctl status study1409-app.service --no-pager
