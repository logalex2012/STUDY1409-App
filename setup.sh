#!/usr/bin/env bash
set -e

PROJECT_DIR="/root/app-pwa/STUDY1409-App"
DOMAIN="student.my1409.ru"

echo "=== Установка nginx и SSL для ${DOMAIN} ==="

if ! command -v nginx &>/dev/null; then
  apt update && apt install -y nginx
fi

if ! command -v certbot &>/dev/null; then
  apt install -y certbot
fi

# Получаем SSL-сертификат (standalone — не трогает конфиг nginx)
systemctl stop nginx
certbot certonly --standalone -d ${DOMAIN} --non-interactive --agree-tos -m admin@${DOMAIN} || \
  certbot certonly --standalone -d ${DOMAIN}
systemctl start nginx

# Устанавливаем конфиг nginx из репозитория
cp "${PROJECT_DIR}/nginx-study1409.conf" /etc/nginx/sites-available/study1409
ln -sf /etc/nginx/sites-available/study1409 /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

echo "=== Готово! https://${DOMAIN} ==="
