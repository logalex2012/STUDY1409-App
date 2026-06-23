import config
import hashlib
import json
import os
import psycopg2
import psycopg2.extras
import psycopg2.pool
import requests as http
import time
import uuid
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import wraps
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from flask import (Flask, render_template, redirect, url_for,
                   request, session, jsonify, Response)

# Инициализация Flask приложения #
app = Flask(__name__, static_folder='s', static_url_path='/s')
_IS_DEV = os.environ.get("FLASK_DEBUG", "0") == "1"

app.config.update(SECRET_KEY=config.SECRET_KEY)
app.config.update(
    SESSION_COOKIE_SECURE=not _IS_DEV,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_PERMANENT=True,
)
app.permanent_session_lifetime = timedelta(days=365)

_base = config.MY1409_BASE
if _base and '://' not in _base:
    _base = 'https://' + _base
MY1409_BASE = _base
_ADMIN_PW_HASH = config.ADMIN_PW_HASH

_MAINTENANCE_FILE = os.path.join(os.path.dirname(__file__), "maintenance.lock")

VAPID_PUBLIC_KEY   = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY  = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_CLAIMS_EMAIL = os.environ.get("VAPID_CLAIMS_EMAIL", "admin@study1409.ru")

_DB_POOL = psycopg2.pool.ThreadedConnectionPool(
    minconn=2,
    maxconn=10,
    dsn=config.DATABASE_URL,
)

@contextmanager
def _db():
    conn = _DB_POOL.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _DB_POOL.putconn(conn)


def _init_db():
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS subscriptions (
                    endpoint TEXT PRIMARY KEY,
                    sub_json JSONB NOT NULL,
                    phone    TEXT,
                    grp      TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS activity_log (
                    id      SERIAL PRIMARY KEY,
                    ts      TIMESTAMPTZ DEFAULT NOW(),
                    phone   TEXT,
                    grp     TEXT,
                    action  TEXT NOT NULL,
                    details TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS activity_pins (
                    id             SERIAL PRIMARY KEY,
                    pin_code       TEXT NOT NULL UNIQUE,
                    student_name   TEXT NOT NULL,
                    student_phone  TEXT NOT NULL DEFAULT '',
                    student_class  TEXT NOT NULL DEFAULT '',
                    activity_name  TEXT NOT NULL,
                    issued_at      TIMESTAMPTZ DEFAULT NOW(),
                    issued_by      TEXT DEFAULT '',
                    is_active      BOOLEAN DEFAULT TRUE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS exit_applications (
                    id               TEXT PRIMARY KEY,
                    student_phone    TEXT NOT NULL DEFAULT '',
                    student_name     TEXT NOT NULL DEFAULT '',
                    student_group    TEXT NOT NULL DEFAULT '',
                    teacher_name     TEXT NOT NULL DEFAULT '',
                    cause            TEXT NOT NULL DEFAULT '',
                    allowed_exit_time TEXT DEFAULT NULL,
                    is_show          BOOLEAN DEFAULT FALSE,
                    is_used          BOOLEAN DEFAULT FALSE,
                    is_expired       BOOLEAN DEFAULT FALSE,
                    created_at       TEXT DEFAULT NULL,
                    used_at          TEXT DEFAULT NULL
                )
            """)
            cur.execute("""
                ALTER TABLE exit_applications
                ADD COLUMN IF NOT EXISTS student_phone TEXT NOT NULL DEFAULT ''
            """)
            cur.execute("""
                ALTER TABLE exit_applications
                ADD COLUMN IF NOT EXISTS is_expired BOOLEAN DEFAULT FALSE
            """)
            cur.execute("""
                ALTER TABLE exit_applications
                ADD COLUMN IF NOT EXISTS used_at TEXT DEFAULT NULL
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS exit_application_requests (
                    id               TEXT PRIMARY KEY,
                    student_phone    TEXT NOT NULL,
                    student_name     TEXT NOT NULL DEFAULT '',
                    student_group    TEXT NOT NULL DEFAULT '',
                    cause            TEXT NOT NULL,
                    allowed_exit_time TEXT NOT NULL,
                    is_rejected      BOOLEAN DEFAULT FALSE,
                    is_deleted       BOOLEAN DEFAULT FALSE,
                    created_at       TEXT DEFAULT NULL,
                    teacher_name     TEXT NOT NULL DEFAULT ''
                )
            """)
            cur.execute("""
                ALTER TABLE exit_application_requests
                ADD COLUMN IF NOT EXISTS student_phone TEXT NOT NULL DEFAULT ''
            """)
            cur.execute("""
                ALTER TABLE exit_application_requests
                ALTER COLUMN student_id DROP NOT NULL
            """)
            cur.execute("""
                ALTER TABLE exit_application_requests
                ALTER COLUMN student_name SET DEFAULT ''
            """)
            cur.execute("""
                ALTER TABLE exit_application_requests
                ALTER COLUMN student_group SET DEFAULT ''
            """)
            cur.execute("""
                ALTER TABLE exit_application_requests
                ALTER COLUMN student_name DROP NOT NULL
            """)
            cur.execute("""
                ALTER TABLE exit_application_requests
                ALTER COLUMN student_group DROP NOT NULL
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS student_profiles (
                    phone           TEXT PRIMARY KEY,
                    surname         TEXT NOT NULL DEFAULT '',
                    name            TEXT NOT NULL DEFAULT '',
                    lastname        TEXT NOT NULL DEFAULT '',
                    group_number    TEXT NOT NULL DEFAULT '',
                    group_letter    TEXT NOT NULL DEFAULT '',
                    class_teacher_name TEXT NOT NULL DEFAULT '',
                    updated_at      TIMESTAMPTZ DEFAULT NOW()
                )
            """)


_init_db()

# ── Rate limiting (in-memory) ──────────────────────────────────
_rl_lock  = Lock()
_rl_admin = defaultdict(list)   # ip    → [timestamps]
_rl_sms   = defaultdict(list)   # phone → [timestamps]


def _rate_ok(store: dict, key: str, limit: int, window: int) -> bool:
    """Возвращает True если запрос разрешён, False если лимит превышен."""
    now = time.time()
    with _rl_lock:
        store[key] = [t for t in store[key] if now - t < window]
        if len(store[key]) >= limit:
            return False
        store[key].append(now)
        return True


_FLAG_DEFAULTS: dict[str, bool] = {
    "passes_enabled":   True,
    "cards_enabled":    True,
    "stranger_enabled": True,
}


def _get_flag(key: str) -> bool:
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM app_settings WHERE key = %s", (key,))
            row = cur.fetchone()
    return row[0] == "true" if row else _FLAG_DEFAULTS.get(key, True)


def _set_flag(key: str, value: bool):
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_settings (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                """,
                (key, "true" if value else "false"),
            )


def _log_activity(action: str, details: str = ""):
    try:
        phone = session.get("phone", "")
        grp   = ""
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO activity_log (phone, grp, action, details) VALUES (%s, %s, %s, %s)",
                    (phone, grp, action, details),
                )
    except Exception:
        pass


def _load_subs():
    with _db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT sub_json FROM subscriptions")
            return [row["sub_json"] for row in cur.fetchall()]


def _save_sub(sub: dict):
    u = sub.get("_user", {})
    sub_copy = {k: v for k, v in sub.items() if k != "_user"}
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO subscriptions (endpoint, sub_json, phone, grp)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (endpoint) DO UPDATE
                    SET sub_json = EXCLUDED.sub_json,
                        phone    = EXCLUDED.phone,
                        grp      = EXCLUDED.grp
                """,
                (sub_copy["endpoint"], json.dumps(sub_copy), u.get("phone", ""), u.get("group", "")),
            )


def _delete_sub(endpoint: str):
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM subscriptions WHERE endpoint = %s", (endpoint,))


def _delete_dead_subs(endpoints: list):
    with _db() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(
                cur, "DELETE FROM subscriptions WHERE endpoint = %s",
                [(e,) for e in endpoints],
            )


# ── Maintenance middleware ─────────────────────────────────────
_MAINTENANCE_BYPASS = {"/admin", "/admin/logout", "/sw.js", "/offline",
                       "/static/favicon.png", "/static/manifest.json",
                       "/help"}

@app.before_request
def check_maintenance():
    if not os.path.exists(_MAINTENANCE_FILE):
        return
    path = request.path
    if session.get("admin"):
        return
    if path in _MAINTENANCE_BYPASS or path.startswith("/static/") or path.startswith("/s/"):
        return
    return render_template("maintenance.html"), 503


# ── Helpers ───────────────────────────────────────────────────
def _my1409_cookies():
    c = session.get("my1409_cookie")
    return {"session": c} if c else {}

def _require_student(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("my1409_cookie"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapped

def _student_obj(u: dict):
    class Student:
        surname      = u.get("surname", "")
        name         = u.get("name", "")
        lastname     = u.get("lastname", "")
        group_number = u.get("group_number", "")
        group_letter = u.get("group_letter", "")
        phone        = u.get("phone", "")
    return Student()


def _sync_and_save_profile(phone: str, cookies: dict):
    """Пытается получить профиль студента из my1409.ru (через существующие API) и сохранить в БД."""
    surname = name = lastname = group_number = group_letter = class_teacher_name = ""

    # 1) Пробуем получить teacher_name и application_id из exit-history
    try:
        r = http.get(f"{MY1409_BASE}/api/student/exit-history", cookies=cookies, timeout=5)
        if r.ok:
            history = r.json()
            if isinstance(history, list) and history:
                class_teacher_name = history[0].get("teacher_name", "")
                # Пробуем получить имя/класс студента из деталей заявки (PUBLIC endpoint)
                for entry in history[:3]:
                    app_id = entry.get("id")
                    if app_id:
                        try:
                            r2 = http.get(f"{MY1409_BASE}/api/student/application/{app_id}", timeout=5)
                            if r2.ok:
                                data = r2.json()
                                if data.get("name"):
                                    parts = data["name"].strip().split()
                                    surname = parts[0] if len(parts) > 0 else ""
                                    name = parts[1] if len(parts) > 1 else ""
                                    lastname = parts[2] if len(parts) > 2 else ""
                                if data.get("group"):
                                    grp = data["group"].strip().split()
                                    group_number = grp[0] if len(grp) > 0 else ""
                                    group_letter = grp[1] if len(grp) > 1 else ""
                                if not class_teacher_name:
                                    class_teacher_name = data.get("teacher_name", "")
                                break
                        except:
                            continue
    except:
        pass

    # 2) Если не получили из exit-history — пробуем exit-requests
    if not name and not surname:
        try:
            r = http.get(f"{MY1409_BASE}/api/student/exit-requests", cookies=cookies, timeout=5)
            if r.ok:
                reqs = r.json()
                if isinstance(reqs, list) and reqs:
                    if not class_teacher_name:
                        class_teacher_name = reqs[0].get("teacher_name", "")
        except:
            pass

    # 3) Если всё ещё нет — парсим /student_page HTML
    if not surname and not name:
        try:
            r = http.get(f"{MY1409_BASE}/student_page", cookies=cookies, timeout=5)
            if r.ok:
                import re
                html = r.text
                m_name = re.search(r'<div class="greeting-name">([^<]+)</div>', html)
                if m_name:
                    parts = m_name.group(1).strip().split()
                    surname = parts[0] if len(parts) > 0 else ""
                    name = parts[1] if len(parts) > 1 else parts[0] if len(parts) > 0 else ""
                    lastname = " ".join(parts[2:]) if len(parts) > 2 else ""
                m_class = re.search(r'<div class="greeting-class">(\d+)\s*([А-ЯЁ])', html)
                if m_class:
                    group_number = m_class.group(1)
                    group_letter = m_class.group(2)
        except:
            pass

    if surname or name or group_number or class_teacher_name:
        with _db() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO student_profiles
                        (phone, surname, name, lastname, group_number, group_letter, class_teacher_name)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (phone) DO UPDATE SET
                        surname=EXCLUDED.surname, name=EXCLUDED.name,
                        lastname=EXCLUDED.lastname, group_number=EXCLUDED.group_number,
                        group_letter=EXCLUDED.group_letter,
                        class_teacher_name=EXCLUDED.class_teacher_name,
                        updated_at=NOW()
                """, (phone, surname, name, lastname, group_number, group_letter, class_teacher_name))
        prof = {"surname": surname, "name": name, "lastname": lastname,
                "group_number": group_number, "group_letter": group_letter,
                "class_teacher_name": class_teacher_name, "phone": phone}
        session["user"] = prof
        session["phone"] = phone
        session.modified = True


# ── Авторизация ──────────────────────────────────────────────
@app.route("/")
def login():
    if session.get("my1409_cookie"):
        return redirect(url_for("apps"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("my1409_cookie", None)
    session.pop("user", None)
    session.pop("phone", None)
    return redirect(url_for("login"))


# ── PWA Login API (proxy → my1409.ru) ─────────────────────────
@app.route("/api/pwa/login/send-code", methods=["POST"])
def pwa_login_send():
    phone = (request.json or {}).get("phone", "")
    # Rate limit: 3 запроса в 60 секунд на номер телефона
    if not _rate_ok(_rl_sms, phone, limit=3, window=60):
        return jsonify({"status": "error", "message": "Слишком много запросов. Подождите минуту."}), 429
    try:
        r = http.post(f"{MY1409_BASE}/api/teacher/login/phone-send",
                      json={"phone": phone}, timeout=10)
        return jsonify(r.json()), r.status_code
    except Exception:
        return jsonify({"status": "error", "message": "Сервер my1409 недоступен"}), 503


@app.route("/api/pwa/login/verify-code", methods=["POST"])
def pwa_login_verify():
    data  = request.json or {}
    phone = data.get("phone", "")
    code  = data.get("code", "")
    try:
        r = http.post(f"{MY1409_BASE}/api/teacher/login/phone-check",
                      json={"phone": phone, "code": code}, timeout=10)
        body = r.json()
        if r.ok and body.get("status") == "success":
            # Сохраняем сессионную куку my1409.ru
            cookie = r.cookies.get("session")
            if cookie:
                # Пересоздаём сессию чтобы предотвратить session fixation
                session.clear()
                session.permanent = True
                session["my1409_cookie"] = cookie
                session["phone"] = phone
                user = body.get("user", {})
                session["user"] = user
                _log_activity("login", phone)
                # Сразу подтягиваем профиль ученика (my1409.ru не возвращает user для student)
                _sync_and_save_profile(phone, {"session": cookie})
        return jsonify(body), r.status_code
    except Exception:
        return jsonify({"status": "error", "message": "Сервер my1409 недоступен"}), 503


# ── Student: локальные endpoints для заявок на выход ──────────
@app.route("/api/student/exit-request", methods=["POST"])
def student_create_exit_request():
    if not session.get("phone"):
        return jsonify({"error": "unauthorized"}), 401
    data = request.json or {}
    cause = data.get("cause", "")
    exit_time = data.get("exit_time", "")
    if not cause or not exit_time:
        return jsonify({"status": "error", "message": "Неверные данные"}), 400
    phone = session.get("phone", "")
    request_id = str(uuid.uuid4())[:8]
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO exit_application_requests
                   (id, student_phone, cause, allowed_exit_time)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                (request_id, phone, cause, exit_time)
            )
    try:
        url = f"{MY1409_BASE}/api/student/exit-request"
        cookies = _my1409_cookies()
        r = http.post(url, json=data, cookies=cookies, timeout=8)
        new_c = r.cookies.get("session")
        if new_c:
            session["my1409_cookie"] = new_c
        if r.ok:
            try:
                return jsonify(r.json()), r.status_code
            except Exception:
                pass
    except Exception:
        pass
    return jsonify({"status": "success", "message": "Заявка отправлена", "id": request_id}), 200


@app.route("/api/student/exit-requests")
def student_get_exit_requests():
    phone = session.get("phone", "")
    with _db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, cause, created_at, allowed_exit_time,
                          is_rejected, teacher_name
                   FROM exit_application_requests
                   WHERE student_phone = %s AND is_deleted = FALSE
                   ORDER BY created_at DESC""",
                (phone,)
            )
            rows = cur.fetchall()
    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "cause": r["cause"] or "",
            "created_at": r["created_at"].strftime("%d.%m.%Y %H:%M") if r["created_at"] else "",
            "allowed_exit_time": r["allowed_exit_time"] or "",
            "is_rejected": r["is_rejected"],
            "teacher_name": r["teacher_name"] or "",
        })
    return jsonify(items), 200


@app.route("/api/student/exit-history")
def student_get_exit_history():
    phone = session.get("phone", "")
    try:
        url = f"{MY1409_BASE}/api/student/exit-history"
        cookies = _my1409_cookies()
        r = http.get(url, cookies=cookies, timeout=8)
        if r.ok:
            try:
                data = r.json()
                if isinstance(data, list):
                    return jsonify(data), 200
            except Exception:
                pass
    except Exception:
        pass
    with _db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, student_name, student_group, teacher_name, cause,
                          allowed_exit_time, is_show, is_used, is_expired,
                          created_at, used_at
                   FROM exit_applications
                   WHERE student_phone = %s
                   ORDER BY created_at DESC""",
                (phone,)
            )
            cached = cur.fetchall()
    items = []
    for c in cached:
        items.append({
            "id": c["id"],
            "cause": c["cause"] or "",
            "created_at": c["created_at"].strftime("%d.%m.%Y %H:%M") if c["created_at"] else "",
            "used_at": c["used_at"].strftime("%d.%m.%Y %H:%M") if c["used_at"] else None,
            "allowed_exit_time": c["allowed_exit_time"] or "",
            "is_used": c["is_used"],
            "is_expired": c["is_expired"],
            "teacher_name": c["teacher_name"] or "",
        })
    return jsonify(items), 200


@app.route("/api/student/application/<application_id>")
def student_cache_application(application_id):
    phone = session.get("phone", "")
    url = f"{MY1409_BASE}/api/student/application/{application_id}"
    cookies = _my1409_cookies()
    try:
        r = http.get(url, cookies=cookies, timeout=8)
        if r.ok:
            try:
                body = r.json()
            except Exception:
                body = None
            if body and isinstance(body, dict) and body.get("name"):
                name = body.get("name", "")
                group = body.get("group", "")
                teacher = body.get("teacher_name", "")
                exit_time = body.get("allowed_exit_time", "")
                with _db() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """INSERT INTO exit_applications
                               (id, student_phone, student_name, student_group,
                                teacher_name, allowed_exit_time)
                               VALUES (%s, %s, %s, %s, %s, %s)
                               ON CONFLICT (id) DO UPDATE SET
                                student_name = EXCLUDED.student_name,
                                student_group = EXCLUDED.student_group,
                                teacher_name = EXCLUDED.teacher_name,
                                allowed_exit_time = EXCLUDED.allowed_exit_time""",
                            (application_id, phone, name, group,
                             teacher, exit_time)
                        )
                return jsonify(body), r.status_code
    except Exception:
        pass
    with _db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM exit_applications WHERE id = %s", (application_id,)
            )
            cached = cur.fetchone()
    if cached:
        return jsonify({
            "name": cached["student_name"],
            "group": cached["student_group"],
            "teacher_name": cached["teacher_name"],
            "allowed_exit_time": cached["allowed_exit_time"],
        })
    return jsonify({"error": "not found"}), 404


# ── Proxy: /api/student/* и /api/vote/* → my1409.ru ──────────
@app.route("/api/student/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"])
def proxy_student(subpath):
    if not session.get("my1409_cookie"):
        return jsonify({"error": "unauthorized"}), 401
    url     = f"{MY1409_BASE}/api/student/{subpath}"
    cookies = _my1409_cookies()
    try:
        if request.method in ("POST", "PUT", "DELETE"):
            r = http.request(request.method, url,
                             json=request.get_json(silent=True),
                             cookies=cookies, timeout=8)
        else:
            r = http.get(url, params=request.args, cookies=cookies, timeout=8)
        new_c = r.cookies.get("session")
        if new_c:
            session["my1409_cookie"] = new_c
        if r.ok and subpath == "update-class" and request.method == "POST":
            data = request.get_json(silent=True) or {}
            if "group_number" in data:
                session["user"]["group_number"] = data["group_number"]
            if "group_letter" in data:
                session["user"]["group_letter"] = data["group_letter"]
            session.modified = True
        try:
            return jsonify(r.json()), r.status_code
        except Exception:
            return Response(r.text, status=r.status_code, mimetype=r.headers.get('content-type', 'text/plain'))
    except http.RequestException:
        return jsonify({"error": "upstream error"}), 502


# ── Proxy: /api/user/sync → обновление session["user"] из my1409.ru ─
@app.route("/api/user/sync")
def sync_user():
    phone = session.get("phone", "")
    cookies = _my1409_cookies()
    if cookies:
        _sync_and_save_profile(phone, cookies)
    # Если всё ещё нет данных в сессии — отдаём из БД
    user = session.get("user", {})
    if user.get("surname") and user.get("group_number"):
        return jsonify({"status": "ok", "source": "session", "user": user})
    if phone:
        with _db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM student_profiles WHERE phone = %s", (phone,))
                row = cur.fetchone()
                if row:
                    user = dict(row)
                    session["user"] = user
                    session.modified = True
                    return jsonify({"status": "ok", "source": "db", "user": user})
    return jsonify({"status": "unchanged"})


@app.route("/api/vote/<path:subpath>", methods=["GET", "POST"])
def proxy_vote(subpath):
    if not session.get("my1409_cookie"):
        return jsonify({"error": "unauthorized"}), 401
    url     = f"{MY1409_BASE}/api/vote/{subpath}"
    cookies = _my1409_cookies()
    try:
        if request.method == "POST":
            r = http.post(url, json=request.get_json(silent=True),
                          cookies=cookies, timeout=8)
        else:
            r = http.get(url, params=request.args, cookies=cookies, timeout=8)
        return jsonify(r.json()), r.status_code
    except http.RequestException:
        return jsonify({"error": "upstream error"}), 502


# ── Proxy: /api/events/my_registrations → my1409.ru ─────────
@app.route("/api/events/my_registrations", methods=["GET"])
def proxy_my_event_registrations():
    if not session.get("my1409_cookie"):
        return jsonify({"error": "unauthorized"}), 401
    u = session.get("user", {})
    phone = u.get("phone", "")
    if not phone:
        return jsonify([])
    try:
        r = http.get(
            f"{MY1409_BASE}/events/api/my_registrations",
            params={"phone": phone},
            cookies=_my1409_cookies(),
            timeout=8,
        )
        return jsonify(r.json()), r.status_code
    except http.RequestException:
        return jsonify({"error": "upstream error"}), 502


# ── Proxy: /api/events/* → my1409.ru ─────────────────────────
@app.route("/api/events/<path:subpath>", methods=["GET", "POST"])
def proxy_events(subpath):
    if not session.get("my1409_cookie"):
        return jsonify({"error": "unauthorized"}), 401
    url     = f"{MY1409_BASE}/api/events/{subpath}"
    cookies = _my1409_cookies()
    try:
        if request.method == "POST":
            r = http.post(url, json=request.get_json(silent=True),
                          cookies=cookies, timeout=8)
        else:
            r = http.get(url, params=request.args, cookies=cookies, timeout=8)
        new_c = r.cookies.get("session")
        if new_c:
            session["my1409_cookie"] = new_c
        return jsonify(r.json()), r.status_code
    except Exception:
        return jsonify({"error": "upstream error"}), 502


# ── Proxy: /api/news → my1409.ru ─────────────────────────────
@app.route("/api/news")
def proxy_news():
    if not session.get("my1409_cookie"):
        return jsonify({"error": "unauthorized"}), 401
    try:
        r = http.get(f"{MY1409_BASE}/api/news",
                     params=request.args,
                     cookies=_my1409_cookies(), timeout=8)
        return jsonify(r.json()), r.status_code
    except Exception:
        return jsonify({"error": "upstream error"}), 502


# ── Proxy: /api/card/* ────────────────────────────────────────
@app.route("/api/card/<path:subpath>", methods=["GET", "POST"])
def proxy_card(subpath):
    if not session.get("my1409_cookie"):
        return jsonify({"error": "unauthorized"}), 401
    url     = f"{MY1409_BASE}/api/card/{subpath}"
    cookies = _my1409_cookies()
    try:
        if request.method == "POST":
            r = http.post(url, json=request.get_json(silent=True),
                          cookies=cookies, timeout=8)
        else:
            r = http.get(url, params=request.args, cookies=cookies, timeout=8)
        return jsonify(r.json()), r.status_code
    except Exception:
        return jsonify({"error": "upstream error"}), 502


# ── Помощь / техподдержка ────────────────────────────────────
@app.route("/help")
@_require_student
def help():
    return render_template("help.html")


# ── Главная (сервисы) ─────────────────────────────────────────
@app.route("/apps")
@app.route("/student_page")
@_require_student
def apps():
    u = session.get("user", {})
    return render_template("student_page.html", user=u)


# ── Заявка на выход (для ученика) ────────────────────────────
@app.route("/create_pass")
@app.route("/create_application")
@_require_student
def create_pass():
    return render_template("create_application.html")


# ── Страница заявки на выход ──────────────────────────────────
@app.route("/application/<application_id>")
@_require_student
def application(application_id):
    return render_template("application.html", application_id=application_id)


# ── 404 страница заявки ───────────────────────────────────────
@app.route("/application-404")
def application_404():
    return render_template("application-404.html")


# ── Страница QR-кода для входа на событие ────────────────────
@app.route("/event_registration/<registration_id>")
@_require_student
def event_registration(registration_id):
    u = session.get("user", {})
    full_name = f'{u.get("surname","")} {u.get("name","")} {u.get("lastname","")}'.strip()
    student_class = f'{u.get("group_number","")}{u.get("group_letter","")}'.strip()
    phone = u.get("phone", "")
    return render_template("event_registration.html",
                          full_name=full_name,
                          student_class=student_class,
                          phone=phone,
                          registration_id=registration_id)


# ── Заказ карты МЭШ ──────────────────────────────────────────
@app.route("/card")
@app.route("/new_card")
@app.route("/card_new")
@_require_student
def card():
    u = session.get("user", {})
    full_name = f'{u.get("surname","")} {u.get("name","")} {u.get("lastname","")}'.strip()
    student_class = f'{u.get("group_number","")}{u.get("group_letter","")}'.strip()
    return render_template("new_card_application.html",
                           full_name=full_name, student_class=student_class)


# ── Настройки аккаунта (для ученика) ─────────────────────────
@app.route("/settings")
@app.route("/settints")
@app.route("/account")
@_require_student
def settings():
    u = session.get("user", {})
    phone = session.get("phone", "")
    # Если в сессии нет данных — подтягиваем из БД
    if not u.get("surname"):
        if phone:
            with _db() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("SELECT * FROM student_profiles WHERE phone = %s", (phone,))
                    row = cur.fetchone()
                    if row:
                        u = dict(row)
    # Если всё ещё пусто — пробуем вытащить из кэша exit_applications
    if not u.get("surname") and phone:
        with _db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("""
                    SELECT student_name, student_group, teacher_name
                    FROM exit_applications
                    WHERE student_phone = %s AND student_name != ''
                    ORDER BY created_at DESC LIMIT 1
                """, (phone,))
                row = cur.fetchone()
                if row:
                    # Парсим student_name вида "Фамилия Имя Отчество"
                    parts = (row["student_name"] or "").strip().split()
                    u["surname"] = parts[0] if len(parts) > 0 else ""
                    u["name"] = parts[1] if len(parts) > 1 else ""
                    u["lastname"] = parts[2] if len(parts) > 2 else ""
                    # Парсим group вида "9 А"
                    grp = (row["student_group"] or "").strip().split()
                    u["group_number"] = grp[0] if len(grp) > 0 else ""
                    u["group_letter"] = grp[1] if len(grp) > 1 else ""
                    u["class_teacher_name"] = row["teacher_name"] or ""
    if u.get("surname"):
        session["user"] = u
        session.modified = True
    # Подставляем телефон из сессии если в профиле нет
    if not u.get("phone"):
        u["phone"] = phone
    return render_template("account.html",
                           student=_student_obj(u),
                           class_teacher_name=u.get("class_teacher_name", ""))


# ── Админ панель ──────────────────────────────────────────────
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
        ip = request.remote_addr or "unknown"
        # Rate limit: 5 попыток за 5 минут с одного IP
        if not _rate_ok(_rl_admin, ip, limit=5, window=300):
            return render_template("admin_login.html",
                                   error="Слишком много попыток. Подождите 5 минут."), 429
        pw = request.form.get("password", "")
        if hashlib.sha256(pw.encode()).hexdigest() == _ADMIN_PW_HASH:
            session["admin"] = True
            return redirect(url_for("admin"))
        return render_template("admin_login.html", error="Неверный пароль")
    if not session.get("admin"):
        return render_template("admin_login.html", error=None)
    return render_template("admin.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("admin"))


# ── Error handlers ───────────────────────────────────────────
@app.errorhandler(502)
def err_502(_):
    return render_template("502.html"), 502


@app.errorhandler(403)
def err_403(_):
    return render_template("403.html"), 403

@app.errorhandler(404)
def err_404(_):
    return render_template("404.html"), 404

@app.errorhandler(500)
def err_500(_):
    return render_template("500.html"), 500


# ── Admin: settings ───────────────────────────────────────────
@app.route("/api/admin/settings", methods=["POST"])
def admin_settings():
    if not session.get("admin"):
        return jsonify({"error": "forbidden"}), 403
    data  = request.json or {}
    key   = data.get("key")
    value = data.get("value")
    if key == "maintenance":
        if value:
            with open(_MAINTENANCE_FILE, "w"):
                pass
        elif os.path.exists(_MAINTENANCE_FILE):
            os.remove(_MAINTENANCE_FILE)
    elif key in _FLAG_DEFAULTS:
        _set_flag(key, bool(value))
    return jsonify({"status": "ok"})


@app.route("/api/admin/settings/state")
def admin_settings_state():
    if not session.get("admin"):
        return jsonify({"error": "forbidden"}), 403
    return jsonify({
        "maintenance":      os.path.exists(_MAINTENANCE_FILE),
        "passes_enabled":   _get_flag("passes_enabled"),
        "cards_enabled":    _get_flag("cards_enabled"),
        "stranger_enabled": _get_flag("stranger_enabled"),
    })


# ── Admin: статистика ──────────────────────────────────────────
@app.route("/api/admin/stats")
def admin_stats():
    if not session.get("admin"):
        return jsonify({"error": "forbidden"}), 403
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM subscriptions")
            subs = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM activity_log WHERE action = 'login'")
            logins = cur.fetchone()[0]
    return jsonify({"push_subscribers": subs, "total_logins": logins})


# ── Admin: журнал активности ───────────────────────────────────
@app.route("/api/admin/activity")
def admin_activity():
    if not session.get("admin"):
        return jsonify({"error": "forbidden"}), 403
    with _db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT ts AT TIME ZONE 'Europe/Moscow' AS ts, phone, grp, action, details
                FROM activity_log ORDER BY ts DESC LIMIT 100
            """)
            rows = cur.fetchall()
    items = [
        {
            "ts":      r["ts"].strftime("%d.%m.%Y %H:%M") if r["ts"] else "",
            "phone":   r["phone"] or "",
            "grp":     r["grp"] or "",
            "action":  r["action"] or "",
            "details": r["details"] or "",
        }
        for r in rows
    ]
    return jsonify({"items": items})


# ── Admin: экспорт CSV ─────────────────────────────────────────
@app.route("/api/admin/activity/export")
def admin_activity_export():
    if not session.get("admin"):
        return jsonify({"error": "forbidden"}), 403
    import csv, io
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ts AT TIME ZONE 'Europe/Moscow', phone, grp, action, details
                FROM activity_log ORDER BY ts DESC
            """)
            rows = cur.fetchall()
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Дата и время", "Телефон", "Класс", "Действие", "Детали"])
    for r in rows:
        w.writerow([
            r[0].strftime("%d.%m.%Y %H:%M:%S") if r[0] else "",
            r[1] or "", r[2] or "", r[3] or "", r[4] or "",
        ])
    return Response(
        out.getvalue().encode("utf-8-sig"),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=activity.csv"},
    )


# ── Admin: значки ──────────────────────────────────
import secrets
import string as _string

_PIN_ACTIVITIES = [
    "Спортивное мероприятие",
    "Творческий конкурс",
    "Олимпиада",
    "Волонтёрство",
    "Конференция",
    "Экскурсия",
    "Дежурство",
    "Актив класса",
    "Школьное мероприятие",
    "Другое",
]

def _gen_pin():
    return "1409-" + "".join(secrets.choice(_string.ascii_uppercase + _string.digits) for _ in range(6))


@app.route("/api/admin/pins", methods=["GET"])
def admin_pins_list():
    if not session.get("admin"):
        return jsonify({"error": "forbidden"}), 403
    search = request.args.get("search", "").strip()
    with _db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if search:
                cur.execute(
                    """SELECT id, pin_code, student_name, student_phone, student_class,
                              activity_name, issued_at AT TIME ZONE 'Europe/Moscow' AS issued_at,
                              issued_by, is_active
                       FROM activity_pins
                       WHERE student_name ILIKE %s OR student_phone ILIKE %s OR pin_code ILIKE %s
                       ORDER BY issued_at DESC LIMIT 200""",
                    (f"%{search}%", f"%{search}%", f"%{search}%"),
                )
            else:
                cur.execute(
                    """SELECT id, pin_code, student_name, student_phone, student_class,
                              activity_name, issued_at AT TIME ZONE 'Europe/Moscow' AS issued_at,
                              issued_by, is_active
                       FROM activity_pins ORDER BY issued_at DESC LIMIT 200"""
                )
            rows = cur.fetchall()
    items = [
        {
            "id": r["id"],
            "pin_code": r["pin_code"],
            "student_name": r["student_name"] or "",
            "student_phone": r["student_phone"] or "",
            "student_class": r["student_class"] or "",
            "activity_name": r["activity_name"] or "",
            "issued_at": r["issued_at"].strftime("%d.%m.%Y %H:%M") if r["issued_at"] else "",
            "issued_by": r["issued_by"] or "",
            "is_active": r["is_active"],
        }
        for r in rows
    ]
    return jsonify({"items": items})


@app.route("/api/admin/pins/generate", methods=["POST"])
def admin_pins_generate():
    if not session.get("admin"):
        return jsonify({"error": "forbidden"}), 403
    data = request.json or {}
    student_name  = data.get("student_name", "").strip()
    student_phone = data.get("student_phone", "").strip()
    student_class = data.get("student_class", "").strip()
    activity_name = data.get("activity_name", "").strip()
    count = max(1, min(int(data.get("count", 1)), 20))

    if not student_name or not activity_name:
        return jsonify({"error": "student_name и activity_name обязательны"}), 400

    pins = []
    with _db() as conn:
        with conn.cursor() as cur:
            for _ in range(count):
                code = _gen_pin()
                cur.execute(
                    """INSERT INTO activity_pins (pin_code, student_name, student_phone, student_class, activity_name, issued_by)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (code, student_name, student_phone, student_class, activity_name, "admin"),
                )
                pins.append(code)

    return jsonify({"status": "ok", "pins": pins})


@app.route("/api/admin/pins/revoke", methods=["POST"])
def admin_pins_revoke():
    if not session.get("admin"):
        return jsonify({"error": "forbidden"}), 403
    pin_id = (request.json or {}).get("id")
    if not pin_id:
        return jsonify({"error": "id обязателен"}), 400
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE activity_pins SET is_active = FALSE WHERE id = %s", (pin_id,))
    return jsonify({"status": "ok"})


# ── Student: мои значки ───────────────────────────────────────
@app.route("/api/student/my_pins")
@_require_student
def student_my_pins():
    u = session.get("user", {})
    phone = u.get("phone", "")
    if not phone:
        return jsonify({"items": []})
    with _db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT pin_code, student_name, activity_name,
                          issued_at AT TIME ZONE 'Europe/Moscow' AS issued_at
                   FROM activity_pins
                   WHERE student_phone = %s AND is_active = TRUE
                   ORDER BY issued_at DESC""",
                (phone,),
            )
            rows = cur.fetchall()
    items = [
        {
            "pin_code": r["pin_code"],
            "student_name": r["student_name"] or "",
            "activity_name": r["activity_name"] or "",
            "issued_at": r["issued_at"].strftime("%d.%m.%Y %H:%M") if r["issued_at"] else "",
        }
        for r in rows
    ]
    return jsonify({"items": items})


# ── Admin: список активностей для значков ───────────────────────────
@app.route("/api/admin/pin-activities")
def admin_pin_activities():
    if not session.get("admin"):
        return jsonify({"error": "forbidden"}), 403
    return jsonify({"activities": _PIN_ACTIVITIES})


# ── Service Worker (нужен в корне для полного scope) ──────────
@app.route("/sw.js")
def service_worker():
    resp = app.send_static_file("sw.js")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Content-Type"]  = "application/javascript"
    return resp


# ── Офлайн-страница ───────────────────────────────────────────
@app.route("/offline")
def offline():
    return render_template("offline.html")


# ── Push: VAPID public key ────────────────────────────────────
@app.route("/api/push/vapid-public-key")
def push_vapid_key():
    return jsonify({"key": VAPID_PUBLIC_KEY})


# ── Push: подписка ────────────────────────────────────────────
@app.route("/api/push/subscribe", methods=["POST"])
@_require_student
def push_subscribe():
    sub = request.json
    if not sub or not sub.get("endpoint"):
        return jsonify({"error": "invalid subscription"}), 400
    u = session.get("user", {})
    sub["_user"] = {
        "phone": u.get("phone", ""),
        "group": f"{u.get('group_number','')}{u.get('group_letter','')}",
    }
    _save_sub(sub)
    return jsonify({"status": "ok"})


# ── Push: отписка ─────────────────────────────────────────────
@app.route("/api/push/unsubscribe", methods=["POST"])
@_require_student
def push_unsubscribe():
    endpoint = (request.json or {}).get("endpoint", "")
    _delete_sub(endpoint)
    return jsonify({"status": "ok"})


# ── Push: отправка (admin) ────────────────────────────────────
@app.route("/api/push/send", methods=["POST"])
def push_send():
    if not session.get("admin"):
        return jsonify({"error": "forbidden"}), 403
    if not VAPID_PUBLIC_KEY or not VAPID_PRIVATE_KEY:
        return jsonify({"error": "VAPID keys not configured"}), 503
    payload = request.json or {}
    title   = payload.get("title", "STUDY1409")
    body    = payload.get("body", "")
    url     = payload.get("url", "/apps")
    tag     = payload.get("tag", "study1409")

    try:
        from pywebpush import webpush
    except ImportError:
        return jsonify({"error": "pywebpush not installed"}), 503

    subs = _load_subs()
    sent = 0
    dead = []
    dead_lock = Lock()
    data = json.dumps({"title": title, "body": body, "url": url, "tag": tag})

    def _send(sub):
        try:
            webpush(
                subscription_info=sub,
                data=data,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{VAPID_CLAIMS_EMAIL}"},
            )
            return True
        except Exception:
            with dead_lock:
                dead.append(sub.get("endpoint"))
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_send, sub) for sub in subs]
        for f in as_completed(futures):
            if f.result():
                sent += 1

    if dead:
        _delete_dead_subs(dead)

    return jsonify({"sent": sent, "removed": len(dead)})

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1", port=1090)
