# STUDY1409-App

PWA-приложение для учеников школы №1409. Работает поверх портала my1409.ru — предоставляет удобный мобильный интерфейс с возможностью установки на устройство.

---

## Возможности

- Авторизация по номеру телефона через SMS-код
- Создание заявок на выход из школы
- Заказ карты МЭШ
- Просмотр и управление аккаунтом
- Push-уведомления
- Офлайн-режим
- Устанавливается на устройство как приложение (PWA)

---

## Технологии

- Python 3, Flask
- PostgreSQL (хранение push-подписок)
- Service Worker (PWA)
- Web Push / VAPID

---

## Запуск

### 1. Установить зависимости

```bash
pip install -r requirements.txt
```

### 2. Создать файл `.env`

```env
SECRET_KEY=ваш_секретный_ключ
ADMIN_PW_HASH=sha256_хеш_пароля_администратора
DATABASE_URL=postgresql://user:password@localhost:5432/study1409
MY1409_BASE=https://my1409.ru
VAPID_PUBLIC_KEY=...
VAPID_PRIVATE_KEY=...
VAPID_CLAIMS_EMAIL=admin@study1409.ru
```

Получить хеш пароля администратора:

```bash
python3 -c "import hashlib; print(hashlib.sha256(b'ваш_пароль').hexdigest())"
```

Для генерации VAPID-ключей:

```bash
python3 generate_vapid.py
```

### 3. Запустить

```bash
python3 main.py
```

Приложение запустится на `http://localhost:1090`.
