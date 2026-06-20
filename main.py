import config
import hashlib
import json
import os
import requests as http
from datetime import timedelta
from functools import wraps
from flask import (Flask, render_template, redirect, url_for,
                   request, session, jsonify, Response)

# Инициализация Flask приложения #
app = Flask(__name__)
app.config.update(SECRET_KEY=config.SECRET_KEY)
app.permanent_session_lifetime = timedelta(days=365)

MY1409_BASE = config.MY1409_BASE
_ADMIN_PW_HASH = hashlib.sha256(b"Lesha123#$@)*&v").hexdigest()

_MAINTENANCE_FILE = os.path.join(os.path.dirname(__file__), "maintenance.lock")

VAPID_PUBLIC_KEY   = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_PRIVATE_KEY  = os.environ.get("VAPID_PRIVATE_KEY", "")
VAPID_CLAIMS_EMAIL = os.environ.get("VAPID_CLAIMS_EMAIL", "admin@study1409.ru")
_SUBS_FILE = os.path.join(os.path.dirname(__file__), "subscriptions.json")


def _load_subs():
    if not os.path.exists(_SUBS_FILE):
        return []
    with open(_SUBS_FILE) as f:
        return json.load(f)

def _save_subs(subs):
    with open(_SUBS_FILE, "w") as f:
        json.dump(subs, f)


# ── Maintenance middleware ─────────────────────────────────────
_MAINTENANCE_BYPASS = {"/admin", "/admin/logout", "/sw.js", "/offline",
                       "/static/favicon.png", "/static/manifest.json"}

@app.before_request
def check_maintenance():
    if not os.path.exists(_MAINTENANCE_FILE):
        return
    path = request.path
    if session.get("admin"):
        return
    if path in _MAINTENANCE_BYPASS or path.startswith("/static/"):
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
    return redirect(url_for("login"))


# ── PWA Login API (proxy → my1409.ru) ─────────────────────────
@app.route("/api/pwa/login/send-code", methods=["POST"])
def pwa_login_send():
    phone = (request.json or {}).get("phone", "")
    try:
        r = http.post(f"{MY1409_BASE}/api/student/login/phone-send",
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
        r = http.post(f"{MY1409_BASE}/api/student/login/phone-check",
                      json={"phone": phone, "code": code}, timeout=10)
        body = r.json()
        if r.ok and body.get("status") == "success":
            # Сохраняем сессионную куку my1409.ru
            cookie = r.cookies.get("session")
            if cookie:
                session.permanent = True
                session["my1409_cookie"] = cookie
                # Данные пользователя (phone-check теперь возвращает их)
                session["user"] = body.get("user", {})
        return jsonify(body), r.status_code
    except Exception:
        return jsonify({"status": "error", "message": "Сервер my1409 недоступен"}), 503


# ── Proxy: /api/student/* и /api/vote/* → my1409.ru ──────────
@app.route("/api/student/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE"])
def proxy_student(subpath):
    if not session.get("my1409_cookie"):
        return jsonify({"error": "unauthorized"}), 401
    url     = f"{MY1409_BASE}/api/student/{subpath}"
    cookies = _my1409_cookies()
    try:
        if request.method in ("POST", "PUT"):
            r = http.request(request.method, url,
                             json=request.get_json(silent=True),
                             cookies=cookies, timeout=15)
        else:
            r = http.get(url, params=request.args, cookies=cookies, timeout=15)
        # Если my1409 обновил куку — сохраняем
        new_c = r.cookies.get("session")
        if new_c:
            session["my1409_cookie"] = new_c
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/vote/<path:subpath>", methods=["GET", "POST"])
def proxy_vote(subpath):
    if not session.get("my1409_cookie"):
        return jsonify({"error": "unauthorized"}), 401
    url     = f"{MY1409_BASE}/api/vote/{subpath}"
    cookies = _my1409_cookies()
    try:
        if request.method == "POST":
            r = http.post(url, json=request.get_json(silent=True),
                          cookies=cookies, timeout=15)
        else:
            r = http.get(url, params=request.args, cookies=cookies, timeout=15)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 502


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
                          cookies=cookies, timeout=15)
        else:
            r = http.get(url, params=request.args, cookies=cookies, timeout=15)
        new_c = r.cookies.get("session")
        if new_c:
            session["my1409_cookie"] = new_c
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 502


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
                          cookies=cookies, timeout=15)
        else:
            r = http.get(url, params=request.args, cookies=cookies, timeout=15)
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 502


# ── DEBUG: проверка сессии (временный маршрут) ───────────────
@app.route("/debug-session")
def debug_session():
    return jsonify({
        "has_cookie": bool(session.get("my1409_cookie")),
        "cookie_value": session.get("my1409_cookie", "")[:20] if session.get("my1409_cookie") else None,
        "has_user": bool(session.get("user")),
        "permanent": session.permanent,
    })


# ── Главная (сервисы) ─────────────────────────────────────────
@app.route("/apps")
@_require_student
def apps():
    u = session.get("user", {})
    return render_template("apps.html", user=u)


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


# ── Заказ карты МЭШ ──────────────────────────────────────────
@app.route("/card")
@app.route("/new_card")
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
    return render_template("account.html",
                           student=_student_obj(u),
                           class_teacher_name=u.get("class_teacher_name", ""))


# ── Админ панель ──────────────────────────────────────────────
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST":
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


# ── Admin: settings (maintenance toggle) ─────────────────────
@app.route("/api/admin/settings", methods=["POST"])
def admin_settings():
    if not session.get("admin"):
        return jsonify({"error": "forbidden"}), 403
    data  = request.json or {}
    key   = data.get("key")
    value = data.get("value")
    if key == "maintenance":
        if value:
            open(_MAINTENANCE_FILE, "w").close()
        elif os.path.exists(_MAINTENANCE_FILE):
            os.remove(_MAINTENANCE_FILE)
    return jsonify({"status": "ok"})


@app.route("/api/admin/settings/state")
def admin_settings_state():
    if not session.get("admin"):
        return jsonify({"error": "forbidden"}), 403
    return jsonify({
        "maintenance": os.path.exists(_MAINTENANCE_FILE),
    })


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
    subs = _load_subs()
    subs = [s for s in subs if s.get("endpoint") != sub.get("endpoint")]
    u = session.get("user", {})
    sub["_user"] = {
        "phone": u.get("phone", ""),
        "group": f"{u.get('group_number','')}{u.get('group_letter','')}",
    }
    subs.append(sub)
    _save_subs(subs)
    return jsonify({"status": "ok"})


# ── Push: отписка ─────────────────────────────────────────────
@app.route("/api/push/unsubscribe", methods=["POST"])
@_require_student
def push_unsubscribe():
    endpoint = (request.json or {}).get("endpoint", "")
    subs = [s for s in _load_subs() if s.get("endpoint") != endpoint]
    _save_subs(subs)
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
        from pywebpush import webpush, WebPushException
    except ImportError:
        return jsonify({"error": "pywebpush not installed"}), 503

    subs    = _load_subs()
    sent    = 0
    dead    = []
    data    = json.dumps({"title": title, "body": body, "url": url, "tag": tag})
    for sub in subs:
        clean = {k: v for k, v in sub.items() if not k.startswith("_")}
        try:
            webpush(
                subscription_info=clean,
                data=data,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{VAPID_CLAIMS_EMAIL}"},
            )
            sent += 1
        except Exception:
            dead.append(sub.get("endpoint"))

    if dead:
        _save_subs([s for s in subs if s.get("endpoint") not in dead])

    return jsonify({"sent": sent, "removed": len(dead)})


if __name__ == "__main__":
    app.run(debug=True, port=1090)
