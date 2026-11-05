import json
import secrets
import sqlite3
import time

from flask import (Blueprint, current_app, jsonify, redirect, render_template,
                   request, session, url_for)

from .db import get_db
from .util import render_cards, slot_data

bp = Blueprint("student", __name__)

REVOKED_TTL = 24 * 3600


def new_code(db):
    """6-значный код; секретный ГСЧ и повтор при коллизии."""
    for _ in range(20):
        code = str(100000 + secrets.randbelow(900000))
        if not db.execute("SELECT 1 FROM sessions WHERE code=?", (code,)).fetchone():
            return code
    raise RuntimeError("Не удалось сгенерировать уникальный код")


def my_session(db):
    code = session.get("code")
    if not code:
        return None
    row = db.execute("SELECT * FROM sessions WHERE code=?", (code,)).fetchone()
    if row is None or row["status"] == "revoked":
        session.pop("code", None)
        return None
    return row


def create_session(db):
    now = time.time()
    ttl = current_app.config["PENDING_TTL_MIN"] * 60
    # чистим протухшее прямо здесь, отдельный cron не нужен
    db.execute("DELETE FROM sessions WHERE status='pending' AND created_at < ?", (now - ttl,))
    db.execute("DELETE FROM sessions WHERE status='revoked' AND created_at < ?", (now - REVOKED_TTL,))

    ip = request.remote_addr

    while True:
        try:
            code = new_code(db)
            db.execute(
                "INSERT INTO sessions (code, status, ip, created_at) VALUES (?,?,?,?)",
                (code, "pending", ip, now),
            )
            break
        except sqlite3.IntegrityError:
            continue
    # потолок на число ожидающих кодов: лишние старые вытесняются, новых посетителей не блокируем
    db.execute(
        "DELETE FROM sessions WHERE status='pending' AND id NOT IN "
        "(SELECT id FROM sessions WHERE status='pending' ORDER BY id DESC LIMIT ?)",
        (current_app.config["MAX_PENDING"],))
    db.commit()
    session["code"] = code
    return db.execute("SELECT * FROM sessions WHERE code=?", (code,)).fetchone()


@bp.get("/")
def index():
    db = get_db()
    row = my_session(db) or create_session(db)

    if row["status"] == "pending":
        return render_template("wait.html", code=row["code"])

    slot = db.execute(
        "SELECT s.*, e.title, e.status AS exam_status, e.cards, e.columns AS exam_columns "
        "FROM slots s JOIN exams e ON e.id = s.exam_id WHERE s.id=?",
        (row["slot_id"],),
    ).fetchone()
    if slot is None or slot["exam_status"] != "open":
        db.execute("UPDATE sessions SET status='revoked' WHERE id=?", (row["id"],))
        db.commit()
        session.pop("code", None)
        return render_template("error.html", e=None,
                               message="Мероприятие завершено или рабочее место снято."), 410

    cards = render_cards(json.loads(slot["cards"]), slot_data(slot),
                         json.loads(slot["exam_columns"]))
    return render_template("dashboard.html", cards=cards, exam=slot["title"], label=slot["label"])


@bp.get("/api/status")
def status():
    row = my_session(get_db())
    return jsonify({"status": row["status"] if row else "gone"})


@bp.post("/logout")
def logout():
    code = session.pop("code", None)
    if code:
        db = get_db()
        db.execute("UPDATE sessions SET status='revoked' WHERE code=?", (code,))
        db.commit()
    return redirect(url_for("student.index"))
