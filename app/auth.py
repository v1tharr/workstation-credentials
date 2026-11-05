import time
from functools import wraps

from flask import abort, current_app, g, redirect, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db

MAX_FAILS = 5
LOCK_SECONDS = 300

# хэш-заглушка, чтобы проверка несуществующего логина занимала столько же времени
_DUMMY_HASH = generate_password_hash("dummy-password")


def check_new_password(pw):
    need = current_app.config["MIN_PASSWORD_LEN"]
    if len(pw) < need:
        raise ValueError(f"Пароль короче {need} символов")


def create_admin(username, password, role="admin"):
    check_new_password(password)
    db = get_db()
    db.execute(
        "INSERT INTO admins (username, pw_hash, role, created_at) VALUES (?,?,?,?)",
        (username, generate_password_hash(password), role, time.time()),
    )
    db.commit()


def set_password(admin_id, password):
    check_new_password(password)
    db = get_db()
    db.execute(
        "UPDATE admins SET pw_hash=?, failed=0, locked_until=0 WHERE id=?",
        (generate_password_hash(password), admin_id),
    )
    db.commit()


def try_login(username, password):
    """Возвращает (строка админа | None, сообщение об ошибке)."""
    db = get_db()
    row = db.execute("SELECT * FROM admins WHERE username=?", (username,)).fetchone()
    if row is None:
        check_password_hash(_DUMMY_HASH, password)
        return None, "Неверный логин или пароль"
    if row["locked_until"] > time.time():
        return None, "Слишком много попыток, подождите несколько минут"
    if not row["active"] or not check_password_hash(row["pw_hash"], password):
        failed = row["failed"] + 1
        lock = time.time() + LOCK_SECONDS if failed >= MAX_FAILS else 0
        db.execute("UPDATE admins SET failed=?, locked_until=? WHERE id=?",
                   (0 if lock else failed, lock, row["id"]))
        db.commit()
        return None, "Неверный логин или пароль"
    db.execute("UPDATE admins SET failed=0, locked_until=0 WHERE id=?", (row["id"],))
    db.commit()
    return row, None


def current_admin():
    if "admin" not in g:
        g.admin = None
        aid = session.get("admin_id")
        if aid:
            g.admin = get_db().execute(
                "SELECT * FROM admins WHERE id=? AND active=1", (aid,)
            ).fetchone()
    return g.admin


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if current_admin() is None:
            session.pop("admin_id", None)
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return wrapper


def owner_required(f):
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        if current_admin()["role"] != "owner":
            abort(403)
        return f(*args, **kwargs)
    return wrapper
