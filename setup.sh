#!/usr/bin/env bash
set -e

PROJECT_DIR="/root/app-pwa/STUDY1409-App"

echo "=== Установка nginx для student.my1409.ru ==="

if ! command -v nginx &>/dev/null; then
  apt update && apt install -y nginx
fi

# Удаляем старый битый конфиг если был
rm -f /etc/nginx/sites-enabled/default /etc/nginx/sites-enabled/student.my1409.ru

cp "${PROJECT_DIR}/nginx-study1409.conf" /etc/nginx/sites-available/study1409
ln -sf /etc/nginx/sites-available/study1409 /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

echo "=== Готово! http://student.my1409.ru ==="
